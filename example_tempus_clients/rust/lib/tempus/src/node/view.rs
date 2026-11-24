//! The Cyclon view of one store, as pure functions (development-plan/tempus-design.md section 3), and one store's
//! steps over them (sections 3 and 10). The rules are those of src/tempus/bees_tempus_view.silica and
//! src/tempus/bees_tempus_store.silica; the tests compare this file with the two independent Python models of the BEES
//! tools and with the recorded outputs of trials/t0_tempus_view and trials/t1_tempus_store.
//! Nothing here makes a random number, reads a clock or knows a peer type: every function that chooses takes its draws
//! as a list of integers and uses one draw per choice, as an index modulo the number of candidates. A missing or
//! negative draw counts as 0.

pub const AGE_MAX: i64 = 65535;

/// One entry of a view: the peer's identity, what describes it (opaque here), and its age in ticks.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ViewEntry<P> {
    pub id: Vec<u8>,
    pub d: P,
    pub age: i64,
}

struct Draws<'a> {
    values: &'a [i64],
    next: usize,
}

impl<'a> Draws<'a> {
    fn new(values: &'a [i64]) -> Draws<'a> {
        Draws { values, next: 0 }
    }

    fn take(&mut self) -> usize {
        let v = self.values.get(self.next).copied().unwrap_or(0);
        self.next += 1;
        if v < 0 { 0 } else { v as usize }
    }
}

/// Every age one higher, stopping at AGE_MAX.
pub fn age_all<P: Clone>(v: &[ViewEntry<P>]) -> Vec<ViewEntry<P>> {
    v.iter().map(|e| ViewEntry { id: e.id.clone(), d: e.d.clone(), age: (e.age + 1).min(AGE_MAX) }).collect()
}

/// k entries drawn without replacement, in the order drawn, and what is left, in order.
fn pick<P: Clone>(v: Vec<ViewEntry<P>>, k: i64, draws: &mut Draws) -> (Vec<ViewEntry<P>>, Vec<ViewEntry<P>>) {
    let mut left = v;
    let mut taken = Vec::new();
    let mut k = k;
    while k > 0 && !left.is_empty() {
        let i = draws.take() % left.len();
        taken.push(left.remove(i));
        k -= 1;
    }
    (taken, left)
}

/// What `select` chose.
pub struct Selection<P> {
    pub partner: ViewEntry<P>,
    pub sent: Vec<ViewEntry<P>>,
    pub rest: Vec<ViewEntry<P>>,
}

/// One tick's choice at the initiator (the caller has aged the view): the partner is the oldest entry (the first
/// draw settles a tie), `sent` are count - 1 others drawn without replacement, `rest` is the view without them.
/// None on an empty view.
pub fn select<P: Clone>(v: &[ViewEntry<P>], count: i64, draws: &[i64]) -> Option<Selection<P>> {
    let top = v.iter().map(|e| e.age).max()?;
    let mut ds = Draws::new(draws);
    let oldest: Vec<usize> = (0..v.len()).filter(|i| v[*i].age == top).collect();
    let p = oldest[ds.take() % oldest.len()];
    let mut others = v.to_vec();
    let partner = others.remove(p);
    let (sent, rest) = pick(others, count - 1, &mut ds);
    Some(Selection { partner, sent, rest })
}

/// The partner's choice: up to count entries drawn without replacement, never the asker's own entry; the second
/// value is the view without them (the asker's old entry, if any, stays in it: the merge replaces it).
pub fn reply_select<P: Clone>(v: &[ViewEntry<P>], count: i64, asker: &[u8], draws: &[i64]) -> (Vec<ViewEntry<P>>, Vec<ViewEntry<P>>) {
    let mut ds = Draws::new(draws);
    let candidates: Vec<ViewEntry<P>> = v.iter().filter(|e| e.id != asker).cloned().collect();
    let (sent, _) = pick(candidates, count, &mut ds);
    let rest = v.iter().filter(|e| !sent.iter().any(|s| s.id == e.id)).cloned().collect();
    (sent, rest)
}

/// The view after a shuffle. Entries for self_id are dropped; a peer received twice is kept once, the younger (the
/// earlier at equal age), at the place of its first arrival; a received entry wins against the view's entry of the
/// same peer only when strictly younger; the result is the winners in arrival order, then the kept entries; then
/// the oldest are evicted down to cap (at equal age the latest in order first).
pub fn merge<P: Clone>(rest: &[ViewEntry<P>], received: &[ViewEntry<P>], self_id: &[u8], cap: i64) -> Vec<ViewEntry<P>> {
    let mut once: Vec<ViewEntry<P>> = Vec::new();
    for e in received.iter().filter(|e| e.id != self_id) {
        match once.iter().position(|x| x.id == e.id) {
            Some(i) => {
                if e.age < once[i].age {
                    once[i] = e.clone();
                }
            }
            None => once.push(e.clone()),
        }
    }
    let have = |id: &[u8]| rest.iter().rev().find(|x| x.id == id).map(|x| x.age);
    let win: Vec<ViewEntry<P>> = once.into_iter().filter(|e| have(&e.id).map(|a| e.age < a).unwrap_or(true)).collect();
    let mut view: Vec<ViewEntry<P>> = win.clone();
    view.extend(rest.iter().filter(|e| !win.iter().any(|w| w.id == e.id)).cloned());
    while view.len() as i64 > cap.max(0) {
        let top = view.iter().map(|e| e.age).max().unwrap_or(0);
        match view.iter().rposition(|e| e.age == top) {
            Some(i) => {
                view.remove(i);
            }
            None => break,
        }
    }
    view
}

/// Ruling NQ-16 (b): a received entry whose peer was just sent, and sent strictly younger, is replaced by the sent one.
pub fn prefer_sent<P: Clone>(received: &[ViewEntry<P>], sent: &[ViewEntry<P>]) -> Vec<ViewEntry<P>> {
    received.iter().map(|e| match sent.iter().find(|s| s.id == e.id) {
        Some(s) if s.age < e.age => s.clone(),
        _ => e.clone(),
    }).collect()
}

/// Entries of `sent` go back at the end of the view, in order, while there is room; one already there is skipped.
pub fn backfill<P: Clone>(v: &[ViewEntry<P>], sent: &[ViewEntry<P>], cap: i64) -> Vec<ViewEntry<P>> {
    let mut view = v.to_vec();
    for e in sent {
        if (view.len() as i64) < cap && !view.iter().any(|x| x.id == e.id) {
            view.push(e.clone());
        }
    }
    view
}

/// One entry enters the view by the merge rules.
pub fn insert<P: Clone>(v: &[ViewEntry<P>], e: &ViewEntry<P>, self_id: &[u8], cap: i64) -> Vec<ViewEntry<P>> {
    merge(v, std::slice::from_ref(e), self_id, cap)
}

/// Up to n entries drawn without replacement; the view is not changed.
pub fn sample<P: Clone>(v: &[ViewEntry<P>], n: i64, draws: &[i64]) -> Vec<ViewEntry<P>> {
    let mut ds = Draws::new(draws);
    pick(v.to_vec(), n, &mut ds).0
}

/// The invariants: at most cap entries, no id twice, no empty id, none for self_id, every age in 0..=AGE_MAX.
pub fn valid<P>(v: &[ViewEntry<P>], self_id: &[u8], cap: i64) -> bool {
    v.len() as i64 <= cap
        && (0..v.len()).all(|i| !v[..i].iter().any(|x| x.id == v[i].id))
        && v.iter().all(|e| !e.id.is_empty() && e.id != self_id && e.age >= 0 && e.age <= AGE_MAX)
}

/// What a tick did.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TickStep<P> {
    /// No draws were given: the tick is skipped whole.
    Skipped,
    /// A shuffle of this store is in flight: the view was aged and nothing else.
    Aged,
    /// The view is empty.
    Empty,
    /// The buffer `out` goes to `partner`; the partner and the sent entries have left the view.
    Shuffle { partner: ViewEntry<P>, out: Vec<ViewEntry<P>> },
}

/// One of a node's three stores. It knows nothing of types, connections, tokens or time: its owner feeds it events
/// and carries out what it answers. `own` says whether the node's own entry belongs in it (true only for the store of
/// the node's own type, ruling OQ-5).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Store<P> {
    pub view: Vec<ViewEntry<P>>,
    pub sent: Vec<ViewEntry<P>>,
    pub partner: Option<ViewEntry<P>>,
    pub me: ViewEntry<P>,
    pub own: bool,
    pub cap: i64,
    pub count: i64,
}

impl<P: Clone> Store<P> {
    pub fn new(self_id: Vec<u8>, self_d: P, own: bool, cap: i64, count: i64) -> Store<P> {
        Store { view: Vec::new(), sent: Vec::new(), partner: None, me: ViewEntry { id: self_id, d: self_d, age: 0 }, own, cap, count }
    }

    /// True while a shuffle this store started is in flight.
    pub fn shuffling(&self) -> bool {
        self.partner.is_some()
    }

    pub fn tick(&mut self, draws: Option<&[i64]>) -> TickStep<P> {
        let draws = match draws {
            Some(d) => d,
            None => return TickStep::Skipped,
        };
        let aged = age_all(&self.view);
        if self.partner.is_some() {
            self.view = aged;
            return TickStep::Aged;
        }
        let sel = match select(&aged, if self.own { self.count } else { self.count + 1 }, draws) {
            Some(s) => s,
            None => return TickStep::Empty,
        };
        self.view = sel.rest;
        self.sent = sel.sent.clone();
        self.partner = Some(sel.partner.clone());
        let mut out = if self.own { vec![self.me.clone()] } else { Vec::new() };
        out.extend(sel.sent);
        TickStep::Shuffle { partner: sel.partner, out }
    }

    /// The partner was unreachable, closed, timed out or violated: it stays out, the other sent entries are put back.
    pub fn failed(&mut self) {
        if self.partner.is_none() {
            return;
        }
        self.view = backfill(&self.view, &self.sent, self.cap);
        self.sent.clear();
        self.partner = None;
    }

    /// The partner's answer. False when it held more than `count` entries, which counts as a failed shuffle.
    pub fn reply(&mut self, received: &[ViewEntry<P>]) -> bool {
        let p = match &self.partner {
            Some(p) => p.clone(),
            None => return true,
        };
        if received.len() as i64 > self.count {
            self.failed();
            return false;
        }
        let mut m = merge(&self.view, &prefer_sent(received, &self.sent), &self.me.id, self.cap);
        if !self.own {
            // ruling NQ-15: the partner that answered re-enters at age 0
            m = insert(&m, &ViewEntry { id: p.id, d: p.d, age: 0 }, &self.me.id, self.cap);
        }
        self.view = backfill(&m, &self.sent, self.cap);
        self.sent.clear();
        self.partner = None;
        true
    }

    /// A partner's shuffle arrives. None when refused (no draws, or more than `count` entries); else the answer.
    pub fn request(&mut self, asker: &[u8], received: &[ViewEntry<P>], draws: Option<&[i64]>) -> Option<Vec<ViewEntry<P>>> {
        let draws = draws?;
        if received.len() as i64 > self.count {
            return None;
        }
        let (sent, rest) = reply_select(&self.view, self.count, asker, draws);
        let m = merge(&rest, &prefer_sent(received, &sent), &self.me.id, self.cap);
        self.view = backfill(&m, &sent, self.cap);
        Some(sent)
    }

    /// Up to n entries (at most `count`); the view is not changed. None when refused.
    pub fn sample(&self, n: i64, draws: Option<&[i64]>) -> Option<Vec<ViewEntry<P>>> {
        let draws = draws?;
        if n < 1 {
            return None;
        }
        Some(sample(&self.view, n.min(self.count), draws))
    }

    pub fn insert(&mut self, e: &ViewEntry<P>) {
        self.view = insert(&self.view, e, &self.me.id, self.cap);
    }

    pub fn drop_peer(&mut self, id: &[u8]) {
        self.view.retain(|e| e.id != id);
    }
}
