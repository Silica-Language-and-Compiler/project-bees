// EXAMPLE ONLY, not for production. See README.md in the directory above.
//
// The view of one store and the steps of one store: the rules of development-plan/tempus-design.md section 3 (the
// Cyclon view, with the rulings OQ-5, OQ-12, NQ-15 and NQ-16), equal in behaviour to the Silica units
// src/tempus/bees_tempus_view.silica and bees_tempus_store.silica. Pure: nothing here reads a clock, makes a random
// number or touches a connection. Every function that chooses takes its draws as a list of numbers and uses one
// draw per choice, as an index modulo the number of candidates; a missing or negative draw counts as 0.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Bees.Tempus
{
    /// <summary>One entry of a view: the peer's identifier as text, what the holder keeps for it, and its age in ticks.</summary>
    public sealed class Held<D>
    {
        public string Id { get; }
        public D Value { get; }
        public int Age { get; }
        public Held(string id, D value, int age) { Id = id; Value = value; Age = age; }
        public override bool Equals(object o) => o is Held<D> h && h.Id == Id && h.Age == Age && EqualityComparer<D>.Default.Equals(h.Value, Value);
        public override int GetHashCode() => Id.GetHashCode() * 31 + Age;
        public override string ToString() => Id + ":" + Age;
    }

    /// <summary>The pure view functions. A view is a list of entries with no identifier twice and none for the node itself.</summary>
    public static class View
    {
        sealed class Draws
        {
            readonly Queue<long> left;
            public Draws(IEnumerable<long> values) { left = new Queue<long>(values ?? Array.Empty<long>()); }
            public long Take()
            {
                long v = left.Count == 0 ? 0 : left.Dequeue();
                return v >= 0 ? v : 0;
            }
        }

        /// <summary>Every age one higher; an age stops at 65535.</summary>
        public static List<Held<D>> AgeAll<D>(IEnumerable<Held<D>> view) => view.Select(e => new Held<D>(e.Id, e.Value, Math.Min(e.Age + 1, Frames.AgeMax))).ToList();

        // k entries drawn without replacement, in the order drawn, and what is left.
        static (List<Held<D>>, List<Held<D>>) Pick<D>(IEnumerable<Held<D>> view, int k, Draws draws)
        {
            var left = view.ToList();
            var taken = new List<Held<D>>();
            while (k > 0 && left.Count > 0)
            {
                int at = (int)(draws.Take() % left.Count);
                taken.Add(left[at]);
                left.RemoveAt(at);
                k -= 1;
            }
            return (taken, left);
        }

        /// <summary>
        /// One tick's choice at the initiator (the caller has aged the view): the partner is the oldest entry (the
        /// first draw settles a tie); length - 1 others are drawn to be sent; rest is the view without them all. The
        /// partner is null on an empty view.
        /// </summary>
        public static (Held<D> Partner, List<Held<D>> Sent, List<Held<D>> Left) Select<D>(IReadOnlyList<Held<D>> view, int length, IEnumerable<long> draws)
        {
            if (view.Count == 0) return (null, new List<Held<D>>(), new List<Held<D>>());
            var ds = new Draws(draws);
            int top = view.Max(e => e.Age);
            var oldest = view.Where(e => e.Age == top).ToList();
            var partner = oldest[(int)(ds.Take() % oldest.Count)];
            var (sent, rest) = Pick(view.Where(e => e.Id != partner.Id), length - 1, ds);
            return (partner, sent, rest);
        }

        /// <summary>The buffer for the partner: the node's own entry at age 0, then the entries chosen.</summary>
        public static List<Held<D>> Outgoing<D>(string selfId, D selfD, IEnumerable<Held<D>> sent)
        {
            var o = new List<Held<D>> { new Held<D>(selfId, selfD, 0) };
            o.AddRange(sent);
            return o;
        }

        /// <summary>The partner's choice: up to length entries, never the asker's own; and the view without them.</summary>
        public static (List<Held<D>> Sent, List<Held<D>> Kept) ReplySelect<D>(IReadOnlyList<Held<D>> view, int length, string asker, IEnumerable<long> draws)
        {
            var (sent, _) = Pick(view.Where(e => e.Id != asker), length, new Draws(draws));
            var gone = new HashSet<string>(sent.Select(e => e.Id));
            return (sent, view.Where(e => !gone.Contains(e.Id)).ToList());
        }

        /// <summary>
        /// The view after a shuffle: entries for the node itself are dropped; a peer in both is kept once, the younger
        /// entry (at equal age the one the node had); the winning received entries come first, in the order of their
        /// first arrival; then the oldest are evicted down to the capacity (at equal age the latest in the view's order).
        /// </summary>
        public static List<Held<D>> Merge<D>(IReadOnlyList<Held<D>> rest, IEnumerable<Held<D>> received, string selfId, int cap)
        {
            var order = new List<string>();
            var best = new Dictionary<string, Held<D>>();
            foreach (var e in received)
            {
                if (e.Id == selfId) continue;
                if (!best.TryGetValue(e.Id, out var had)) { order.Add(e.Id); best[e.Id] = e; }
                else if (e.Age < had.Age) best[e.Id] = e;
            }
            var have = rest.ToDictionary(e => e.Id, e => e.Age);
            var win = order.Select(id => best[id]).Where(e => !have.TryGetValue(e.Id, out int a) || e.Age < a).ToList();
            var won = new HashSet<string>(win.Select(e => e.Id));
            var view = win.Concat(rest.Where(e => !won.Contains(e.Id))).ToList();
            while (view.Count > cap)
            {
                int top = view.Max(e => e.Age);
                view.RemoveAt(view.FindLastIndex(e => e.Age == top));
            }
            return view;
        }

        /// <summary>Ruling NQ-16: a received entry whose peer was just sent, the sent one strictly younger, becomes the sent one.</summary>
        public static List<Held<D>> PreferSent<D>(IEnumerable<Held<D>> received, IEnumerable<Held<D>> sent)
        {
            var ages = new Dictionary<string, Held<D>>();
            foreach (var e in sent) ages.TryAdd(e.Id, e);
            return received.Select(e => ages.TryGetValue(e.Id, out var s) && s.Age < e.Age ? s : e).ToList();
        }

        /// <summary>Entries of sent go back at the end of the view, in order, while there is room; one already there is skipped.</summary>
        public static List<Held<D>> Backfill<D>(IEnumerable<Held<D>> view, IEnumerable<Held<D>> sent, int cap)
        {
            var o = view.ToList();
            foreach (var e in sent) if (o.Count < cap && !o.Any(x => x.Id == e.Id)) o.Add(e);
            return o;
        }

        /// <summary>One entry enters the view by the merge rules.</summary>
        public static List<Held<D>> Insert<D>(IReadOnlyList<Held<D>> view, Held<D> e, string selfId, int cap) => Merge(view, new[] { e }, selfId, cap);

        /// <summary>Up to n entries drawn without replacement; the view is not changed.</summary>
        public static List<Held<D>> Sample<D>(IEnumerable<Held<D>> view, int n, IEnumerable<long> draws) => Pick(view, n, new Draws(draws)).Item1;

        /// <summary>At most cap entries, no identifier twice, none empty, none for the node itself, every age 0 to 65535.</summary>
        public static bool Valid<D>(IReadOnlyList<Held<D>> view, string selfId, int cap) =>
            view.Count <= cap && view.Select(e => e.Id).Distinct().Count() == view.Count &&
            view.All(e => e.Id.Length > 0 && e.Id != selfId && e.Age >= 0 && e.Age <= Frames.AgeMax);
    }

    /// <summary>What one tick of a store did.</summary>
    public enum TickKind
    {
        /// <summary>no tick draws: the tick was skipped whole</summary>
        Skipped,
        /// <summary>a shuffle of this store is in flight: the view was aged and nothing else</summary>
        Aged,
        /// <summary>the view is empty: nothing to do in this store</summary>
        Empty,
        /// <summary>a shuffle begins: dial the partner and send it the buffer</summary>
        Shuffle
    }

    public sealed class Tick<D>
    {
        public TickKind Kind; public Held<D> Partner; public List<Held<D>> Buffer;
    }

    /// <summary>
    /// One store's state and steps. Own says whether the node's own entry belongs in this store (true only for the
    /// store of the node's own type, ruling OQ-5). The two sets of draws are each used once and then gone until the
    /// holder gives new ones: nothing is ever chosen without a draw.
    /// </summary>
    public sealed class Store<D>
    {
        public string SelfId { get; }
        public D SelfD;
        public bool Own { get; }
        public int Cap { get; }
        public int Count { get; }
        public List<Held<D>> Entries = new List<Held<D>>();
        public List<Held<D>> Sent = new List<Held<D>>();
        /// <summary>Set while a shuffle this store started is in flight.</summary>
        public Held<D> Partner;
        public IReadOnlyList<long> TickDraws, ReplyDraws;

        public Store(string selfId, D selfD, bool own, int cap, int count) { SelfId = selfId; SelfD = selfD; Own = own; Cap = cap; Count = count; }

        public bool InFlight => Partner != null;

        public void Insert(Held<D> e) { Entries = View.Insert(Entries, e, SelfId, Cap); }

        public void Drop(string id) { Entries = Entries.Where(e => e.Id != id).ToList(); }

        public Tick<D> Tick()
        {
            var draws = TickDraws;
            if (draws == null) return new Tick<D> { Kind = TickKind.Skipped };
            var aged = View.AgeAll(Entries);
            if (Partner != null) { Entries = aged; return new Tick<D> { Kind = TickKind.Aged }; }
            if (aged.Count == 0) return new Tick<D> { Kind = TickKind.Empty };
            var sel = View.Select(aged, Own ? Count : Count + 1, draws);
            TickDraws = null;
            Entries = sel.Left; Sent = sel.Sent; Partner = sel.Partner;
            return new Tick<D> { Kind = TickKind.Shuffle, Partner = sel.Partner, Buffer = Own ? View.Outgoing(SelfId, SelfD, sel.Sent) : sel.Sent };
        }

        /// <summary>The partner was unreachable, closed, timed out or violated: it stays out, the other sent entries go back.</summary>
        public void Failed()
        {
            if (Partner == null) return;
            Entries = View.Backfill(Entries, Sent, Cap);
            Sent = new List<Held<D>>(); Partner = null;
        }

        /// <summary>The partner's answer. False when it held more entries than the shuffle length, which counts as failed.</summary>
        public bool Reply(IReadOnlyList<Held<D>> received)
        {
            var p = Partner;
            if (p == null) return true;
            if (received.Count > Count) { Failed(); return false; }
            var merged = View.Merge(Entries, View.PreferSent(received, Sent), SelfId, Cap);
            // ruling NQ-15: in a store that is not of the node's own type the partner that answered re-enters at age 0
            if (!Own) merged = View.Insert(merged, new Held<D>(p.Id, p.Value, 0), SelfId, Cap);
            Entries = View.Backfill(merged, Sent, Cap);
            Sent = new List<Held<D>>(); Partner = null;
            return true;
        }

        /// <summary>A partner's shuffle: the entries answered, or null when refused (too many entries, or no reply draws).</summary>
        public List<Held<D>> Request(string asker, IReadOnlyList<Held<D>> received)
        {
            var draws = ReplyDraws;
            if (received.Count > Count || draws == null) return null;
            var (o, kept) = View.ReplySelect(Entries, Count, asker, draws);
            ReplyDraws = null;
            Entries = View.Backfill(View.Merge(kept, View.PreferSent(received, o), SelfId, Cap), o, Cap);
            return o;
        }

        /// <summary>Up to n entries (at most the shuffle length); the view is not changed. Null when refused.</summary>
        public List<Held<D>> Sample(int n)
        {
            var draws = ReplyDraws;
            if (n < 1 || draws == null) return null;
            var o = View.Sample(Entries, Math.Min(n, Count), draws);
            ReplyDraws = null;
            return o;
        }
    }
}
