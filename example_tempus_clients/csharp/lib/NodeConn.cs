// EXAMPLE ONLY, not for production. See README.md in the directory above.
//
// One tempus/1 connection of a node (design sections 4, 5, 8 and 10), dialed or accepted: the same until the request.
// The order, the checks, the audit events and their texts are those of src/tempus/dangerous_bees_tempus_conn.silica
// and of the TLS link under it. Any violation closes with no reply (the one exception is key_rotated) and writes one
// audit line. It runs on a thread of its own with copies of the node's values (ConnValues), and blocks only on its
// own connection, which has ONE time bound from the dial or the accept to the close (ruling NQ-14).
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Sockets;

namespace Bees.Tempus
{
    public static class NodeChecks
    {
        /// <summary>Why a descriptor's token is refused before any key operation, in the Silica node's order and words; null when it passes.
        public static string PreWhy(Descriptor d, byte[] kid, long now, long skew, string want, out Token token)
        {
            token = null;
            try { token = Frames.ReadToken(d.Token); } catch (Refused e) { return e.Why; }
            if (!token.Kid.AsSpan().SequenceEqual(kid)) return "key_rotated";
            if (now < token.Nbf - skew) return "the token is not valid yet";
            if (now >= token.Exp + skew) return "the token has expired";
            if (!token.Sub.AsSpan().SequenceEqual(d.Pub)) return "sub is not the peer's key";
            if (want != null && token.Typ != want) return "typ is not the store's type";
            return null;
        }

        /// Why a gossiped entry of the named store does not verify without contact; null when it does.
        public static string EntryWhy(Descriptor d, string store, byte[] kid, byte[] producerKey, long now, long skew)
        {
            string why = PreWhy(d, kid, now, skew, store, out Token t);
            if (why != null) return why;
            if (!Crypto.PeerId(d.Pub).AsSpan().SequenceEqual(d.Id)) return "id is not the SHA-512 of pub";
            if (!Crypto.Ed25519Verify(producerKey, t.Payload, t.Sig)) return "the signature does not verify";
            return null;
        }

        // The atoms a program that is a Silica TEMPUS node holds for the wire: those of src/tempus/bees_tempus.atoms and
        // every atom of src/trust/bees_trust.atoms, in the order of those two files. The Silica reader refuses a map that names any other atom as
        // unknown_atom, which is what a production node says of the test unit's tick and clock frames; this set lets
        // this node say the same.
        static readonly HashSet<string> WireAtoms = new HashSet<string>
        {
            "advert", "pop_challenge", "pop_response", "key_rotated", "shuffle", "shuffle_reply", "sample", "sample_reply", "done",
            "tempus_edge", "tempus_bridge", "tempus_sentinel", "d", "id", "pub", "addr", "nonce", "sig", "kid", "store", "entries", "age", "n", "sub", "typ",
            "nbf", "exp", "t", "ver", "req_id", "m", "f", "a", "args", "opts", "value", "token", "deadline_ms", "hello", "token_present", "token_issue",
            "call", "cast", "result", "goaway", "erlang", "bad_version", "truncated", "trailing_bytes", "bad_tag", "too_large", "too_deep", "too_long",
            "out_of_range", "unknown_atom", "bad_variant", "missing_field", "duplicate_field", "unknown_field", "unsupported", "ok", "error", "dns_error",
            "connect_failed", "closed", "timeout", "protocol_error", "server_not_pinned"
        };

        static bool Strange(Term x)
        {
            switch (x)
            {
                case TAtom a: return !WireAtoms.Contains(a.Name);
                case TList l: return l.Items.Any(Strange);
                case TMap m: return m.Fields.Any(f => !WireAtoms.Contains(f.Key) || Strange(f.Value));
                default: return false;
            }
        }

        /// The name of a frame's kind (the atom under `t`), or null when the body is not one well-formed map that names
        /// a kind. why says why such a body is no request, in the Silica reader's words.
        public static string KindOf(byte[] bytes, out string why)
        {
            TMap m;
            try
            {
                m = Etf.Decode(bytes) as TMap;
                if (m == null) { why = "bad_tag"; return null; }
            }
            catch (Refused e) { why = e.Why; return null; }
            if (Strange(m)) { why = "unknown_atom"; return null; }
            why = "unknown kind";
            return (m.Get("t") as TAtom)?.Name;
        }
    }

    internal sealed class NodeConn
    {
        sealed class Ended : Exception
        {
            public string Event; public byte[] Kid;
            public Ended(string ev, byte[] kid = null) { Event = ev; Kid = kid; }
        }

        readonly TempusNode node;
        readonly ConnValues v;
        readonly string tag;
        Descriptor peer;
        Conn conn;
        Certificate certificate;

        internal NodeConn(TempusNode node, ConnValues v, string tag) { this.node = node; this.v = v; this.tag = tag; }

        void Audit(string ev, string what) => node.Say("[tempus audit] " + ev + " peer=" + (peer?.Id8() ?? "-") + " " + what + " " + tag);

        Ended Refuse(string ev, string what)
        {
            Audit(ev, what);
            return new Ended(ev);
        }

        // TLS on a connected socket, and what tempus/1 requires of it; Ended after the audit line.
        void Handshake(Socket socket, bool client)
        {
            string side = client ? "client" : "server";
            conn = new Conn(socket, client ? node.ClientContext : node.ServerContext, client, v.Deadline);
            var stop = conn.Handshake();
            if (stop != Stop.None)
            {
                string why = conn.Why;
                if (stop == Stop.Timeout) throw Refuse("timeout", "stage tls_handshake, as " + side);
                if (stop == Stop.TlsFailed)
                {
                    // the listener's own refusal of the dialer's protocols (the fatal alert of the ALPN callback)
                    if (why.Contains("no application protocol") || why.Contains("callback failed"))
                        throw Refuse("alpn_mismatch", "the peer did not agree on ALPN tempus/1, as " + side);
                    if (why.Contains("peer did not return a certificate"))
                        throw Refuse("tls_verify_failed", "the peer presented no certificate, as " + side);
                    throw Refuse("tls_handshake_failed", "the TLS 1.3 handshake failed (alert, version, group, suite or signature outside the tempus/1 profile), as " + side);
                }
                throw Refuse("closed_by_peer", "stage tls_handshake, as " + side);
            }
            if (conn.SelectedAlpn != Tls.Alpn) throw Refuse("alpn_mismatch", "the peer did not agree on ALPN tempus/1, as " + side);
            certificate = conn.PeerCertificate();
            if (certificate == null) throw Refuse("tls_verify_failed", "the peer presented no certificate, as " + side);
            if (!string.Equals(conn.GroupName, Tls.Group, StringComparison.OrdinalIgnoreCase))
                throw Refuse("tls_group_refused", "the connection did not negotiate X25519MLKEM768, the only key exchange of the tempus/1 profile, as " + side);
            if (certificate.Ed25519Key == null) throw Refuse("tempus_cert_key", "the peer certificate's key is not Ed25519, as " + side);
            Audit("tls_established", conn.TlsVersion + " " + Tls.Group + " " + conn.SuiteName + " alpn " + Tls.Alpn + ", mutual, as " + side);
        }

        byte[] Next(string stage)
        {
            var body = conn.Read(out Stop stop);
            if (body != null) return body;
            if (stop == Stop.Oversize) throw Refuse("protocol_error", "frame refused before decoding: too_large");
            if (stop == Stop.Timeout) throw Refuse("timeout", "stage " + stage);
            throw Refuse("closed_by_peer", "stage " + stage);
        }

        T Read<T>(string ev, byte[] bytes, int count) where T : Body
        {
            try { return (T)Frames.ReadBody(bytes, count); }
            catch (Refused e) { throw Refuse(ev, e.Why); }
            catch (InvalidCastException) { throw Refuse(ev, "unknown kind"); }
        }

        // Admission, the same at both ends (design sections 4 and 5). Returns the type in the peer's token.
        string Admit()
        {
            conn.Send(Frames.Frame(Frames.Advert(v.Me.Descriptor())));
            var first = Next("advert");
            if (NodeChecks.KindOf(first, out _) != "advert") throw Refuse("protocol_error", "the first frame is not an advert");
            var d = Read<Body.Advert>("protocol_error", first, Frames.EntriesMax).D;
            peer = d;
            // the channel binding: the advert's pub must be the key of the certificate the handshake proved the peer holds
            if (!certificate.Ed25519Key.AsSpan().SequenceEqual(d.Pub)) throw Refuse("binding_refused", "the advert's pub is not the key of the peer's TLS certificate");
            string why = NodeChecks.PreWhy(d, v.Kid, v.Now, v.Skew, null, out Token token);
            if (why == "key_rotated")
            {
                // the one exception to silence: one key_rotated frame, then what the peer still sends is read and dropped
                // until it closes or the connection's bound passes, so that a reset cannot destroy the frame
                conn.Send(Frames.Frame(Frames.KeyRotated(v.Kid)));
                Audit("key_rotated", "the peer's token is under another kid; it was told the current one");
                while (conn.Read(out _) != null) { }
                throw new Ended("key_rotated_sent");
            }
            if (why != null) throw Refuse("admission_refused", why);
            string typ = token.Typ;
            int listed = v.Whitelist.ToList().IndexOf(certificate.Fingerprint);
            if (typ == "tempus_edge" && listed >= 0) throw Refuse("whitelist_reject", "a certificate of the tempus whitelist with a token whose typ is not tempus_bridge or tempus_sentinel");
            if (typ != "tempus_edge" && listed < 0) throw Refuse("whitelist_reject", "a tempus_bridge or tempus_sentinel token under a certificate that is not in the tempus whitelist");
            if (!Crypto.PeerId(d.Pub).AsSpan().SequenceEqual(d.Id)) throw Refuse("admission_refused", "id is not the SHA-512 of pub");
            if (!Crypto.Ed25519Verify(v.ProducerKey, token.Payload, token.Sig)) throw Refuse("admission_refused", "the signature does not verify");
            var nonce = node.Nonce();
            if (nonce == null || nonce.Length != 32) throw Refuse("internal_error", "random bytes refused");
            conn.Send(Frames.Frame(Frames.Challenge(nonce)));
            var second = Next("challenge");
            switch (NodeChecks.KindOf(second, out _))
            {
                case "key_rotated":
                {
                    var named = Read<Body.KeyRotated>("protocol_error", second, Frames.EntriesMax).Kid;
                    Audit("key_rotated", "the peer says this node's token is under another kid than its current one");
                    throw new Ended("key_rotated", named);
                }
                case "pop_challenge": break;
                default: throw Refuse("protocol_error", "a challenge was expected");
            }
            var theirs = Read<Body.Challenge>("protocol_error", second, Frames.EntriesMax).Nonce;
            conn.Send(Frames.Frame(Frames.Response(v.Me.Prove(theirs))));
            var third = Next("response");
            if (NodeChecks.KindOf(third, out _) != "pop_response") throw Refuse("pop_failed", "a response was expected");
            var sig = Read<Body.Response>("pop_failed", third, Frames.EntriesMax).Sig;
            if (!Crypto.Ed25519Verify(d.Pub, Crypto.Concat(nonce, d.Token), sig)) throw Refuse("pop_failed", "the proof of possession does not verify");
            Audit("admitted", typ + (listed >= 0 ? ", tempus whitelist entry " + listed : ", token and proof of possession"));
            return typ;
        }

        // A frame of entries: its bounds, then every entry verified without contact. One bad entry refuses the whole frame.
        Body.Entries Entries(byte[] bytes)
        {
            var b = Read<Body.Entries>("protocol_error", bytes, v.Count);
            for (int i = 0; i < b.List.Count; i++)
            {
                string why = NodeChecks.EntryWhy(b.List[i].D, b.Store, v.Kid, v.ProducerKey, v.Now, v.Skew);
                if (why != null) throw Refuse("entry_refused", "entry " + i + ": " + why);
            }
            return b;
        }

        internal Dialed Dial(string addr, byte[] request)
        {
            var socket = Client.Connect(Tls.EndPoint(addr), v.Deadline, out _);
            if (socket == null) return new Dialed { Failed = "connect_failed" };
            try
            {
                try { Handshake(socket, true); }
                catch (Ended) { return new Dialed { Failed = "connect_failed" }; }
                string typ = Admit();
                conn.Send(Frames.Frame(request));
                var reply = Next("reply");
                switch (NodeChecks.KindOf(reply, out _))
                {
                    case "shuffle_reply":
                    case "sample_reply":
                        return new Dialed { Replied = true, Reply = Entries(reply), Peer = peer, Typ = typ };
                    case "done":
                    case "result":
                        return new Dialed { Replied = true, Reply = null, Peer = peer, Typ = typ };    // a reply of another kind: no entries
                    default:
                        throw Refuse("protocol_error", "the reply is not a reply frame");
                }
            }
            catch (Ended e)
            {
                return e.Kid != null ? new Dialed { RotatedKid = e.Kid } : new Dialed { Failed = e.Event };
            }
            finally
            {
                if (conn != null) conn.Close(); else try { socket.Close(); } catch (Exception) { }
            }
        }

        /// refusal: why the node closes this connection at once (its inflight limit, or its clock), or null to serve
        /// it. release is called once when the connection has ended, before the lingering close, so that the node's
        /// count of connections in hand falls at once.
        internal void Accepted(Socket raw, string refusal, int cid, Action release)
        {
            try
            {
                Handshake(raw, false);
                switch (refusal)
                {
                    case "inflight_refused": throw Refuse(refusal, "more accepted connections than inflight_max: closed at once");
                    case "clock_refused": throw Refuse(refusal, "the system clock cannot be read: closed at once");
                    case "clock_stopped": throw Refuse(refusal, "the node stopped after its system clock went back: closed at once");
                }
                string typ = Admit();
                var bytes = Next("request");
                string kind = NodeChecks.KindOf(bytes, out string why);
                PeerRequest rq;
                switch (kind)
                {
                    case "shuffle":
                        rq = new PeerRequest { Cid = cid, Kind = kind, Body = Entries(bytes), Peer = peer, Typ = typ };
                        break;
                    case "sample":
                    {
                        Body body = null; string bad = "";
                        try { body = Frames.ReadBody(bytes, Frames.EntriesMax); } catch (Refused e) { bad = e.Why; }
                        rq = new PeerRequest { Cid = cid, Kind = kind, Body = body, Why = bad, Peer = peer, Typ = typ };
                        break;
                    }
                    case "call":
                    case "cast":
                        rq = new PeerRequest { Cid = cid, Kind = kind, Peer = peer, Typ = typ };
                        break;
                    default:
                        // a frame of no kind of tempus/1, the test unit's tick and clock among them: refused like any
                        // frame that is not a request. This extension holds no code that could do otherwise.
                        throw Refuse("protocol_error", "not a request: " + why);
                }
                node.Request(rq);
                // while the node works on the request the bound is the node's: it always answers
                while (!rq.Answer.Task.Wait(200)) if (node.IsClosed) throw new Ended("closed");
                var reply = rq.Answer.Task.Result;
                if (reply != null) conn.Send(Frames.Frame(reply));
            }
            catch (Ended e)
            {
                if (e.Kid != null) node.Rotated(e.Kid);
            }
            finally
            {
                release();
                if (conn != null) conn.Close(); else try { raw.Close(); } catch (Exception) { }
            }
        }
    }
}
