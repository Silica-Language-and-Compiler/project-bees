#!/usr/bin/env python3
"""A hostile TRUST server for the `hostile_b1` and `hostile_session` scenarios of trials/n5_trust_mux (fuzzer finding F1-3,
development-plan/spikes/F1-fuzzer.md): every connection is answered by a fixed script, chosen by the connection's number, with
an answer a correct client must refuse in the token step or in the frame after it, followed at once by more bytes; then the
connection is closed. Before the fix a refused answer could end the client's connection actor (`tcli`, or `mcli` on a session
node) with `actor_not_found` (SD-43's family): the golden of the client shows one outcome per call and no actor failure report.

    hostile_server.py [PORT]        (default: tools/trial_ports.py, n5_trust_mux +0: node s's address, pinned by nodes c and d; scenarios run one at a time)

Plaintext test identity as N3 (the client writes a 64-byte stand-in fingerprint first). It prints `listening on 127.0.0.1:PORT`
once bound, one line per connection, and ends on `exit` (or end of file) on its standard input. Deterministic: the answer
depends on the connection's number only, and the client makes its calls one after another.
"""
import os
import select
import socket
import struct
import sys
import time


def atom(name):
    b = name.encode()
    return bytes([119, len(b)]) + b                      # SMALL_ATOM_UTF8_EXT


def binary(b):
    return bytes([109]) + struct.pack(">I", len(b)) + b  # BINARY_EXT


def integer(n):
    return bytes([97, n]) if 0 <= n < 256 else bytes([98]) + struct.pack(">i", n)


def emap(pairs):
    return bytes([116]) + struct.pack(">I", len(pairs)) + b"".join(k + v for k, v in pairs)


def term(body):
    return bytes([131]) + body


def f4(body):
    return struct.pack(">I", len(body)) + body


TOKEN = bytes(range(48))


def token_issue(tok_term):
    return f4(term(emap([(atom("t"), atom("token_issue")), (atom("token"), tok_term), (atom("ver"), integer(1))])))


def result(rid, n):
    return f4(term(emap([(atom("req_id"), binary(rid)), (atom("t"), atom("result")), (atom("value"), integer(n)), (atom("ver"), integer(1))])))


# kind -> (hello form, token form); each form is a function of the request id and the value
KINDS = {
    # the fuzzer's case 5 (seed 1): a token_issue whose token is an atom, then a result
    "token_not_binary": (lambda rid, n: token_issue(atom("zz_fuzz_7e1ae")) + result(rid, n),
                         lambda rid, n: token_issue(atom("zz_fuzz_7e1ae")) + result(rid, n)),
    # the fuzzer's case 9 (seed 1): a result where the token_issue must be (hello form); a result for another request id
    # (token form, where a result alone would be a right answer)
    "no_token_issue": (lambda rid, n: result(rid, n),
                       lambda rid, n: result(b"z" * len(rid), n) + result(rid, n)),
    # a good token step, then a length above the client's frame_size_max (4096) in front of a result: a framing refusal
    "over_length": (lambda rid, n: token_issue(binary(TOKEN)) + struct.pack(">I", 0xFFFFFFFF) + result(rid, n),
                    lambda rid, n: struct.pack(">I", 0xFFFFFFFF) + result(rid, n)),
    # a frame that is not a map (an empty list), then a result
    "not_a_map": (lambda rid, n: f4(term(bytes([106]))) + result(rid, n),
                  lambda rid, n: f4(term(bytes([106]))) + result(rid, n)),
    # a right answer: the probe after the hostile ones (the next call works)
    "good": (lambda rid, n: token_issue(binary(TOKEN)) + result(rid, n),
             lambda rid, n: result(rid, n)),
}
HOSTILE = ["token_not_binary", "no_token_issue", "over_length", "not_a_map"]
SCRIPT = HOSTILE * 3 + ["good"] + HOSTILE + ["good"]


def frames_of(data):
    out, pos = [], 0
    while pos + 4 <= len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        if pos + 4 + n > len(data):
            break
        out.append(data[pos + 4:pos + 4 + n])
        pos += 4 + n
    return out


def request_id(body):
    """the req_id binary of a request frame (the value after the atom req_id), or None"""
    k = atom("req_id") + bytes([109])
    i = body.find(k)
    if i < 0:
        return None
    i += len(k)
    n = struct.unpack(">I", body[i:i + 4])[0]
    return body[i + 4:i + 4 + n]


def say(s):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def serve(c, k):
    c.settimeout(0.05)
    data, frames, end = b"", [], time.monotonic() + 3.0
    while len(frames) < 2 and time.monotonic() < end:
        try:
            d = c.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            break
        if not d:
            break
        data += d
        frames = frames_of(data[64:]) if len(data) > 64 else []
    kind = SCRIPT[k - 1] if k <= len(SCRIPT) else "good"
    if len(frames) < 2:
        say("conn %d: the token step and a request did not arrive; closed" % k)
        c.close()
        return
    first, req = frames[0], frames[1]
    hello = atom("hello") in first
    offer = atom("goaway") in first
    rid = request_id(req)
    say("conn %d: %s%s, then a request; answered %s" % (k, "hello" if hello else "token_present", " with the session offer" if offer else "", kind))
    if rid is not None:
        c.sendall(KINDS[kind][0 if hello else 1](rid, 100 + k))
    time.sleep(0.05)                                     # the answer leaves before the close
    c.close()


def main():
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
        import trial_ports
        port = trial_ports.port("n5_trust_mux", 0)
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", port))
    ls.listen(8)
    say("listening on 127.0.0.1:%d (a hostile TRUST server, %d scripted answers)" % (port, len(SCRIPT)))
    k = 0
    while True:
        r, _, _ = select.select([ls, sys.stdin], [], [], 0.5)
        if sys.stdin in r:
            line = sys.stdin.readline()
            if not line or line.strip() == "exit":
                break
        if ls in r:
            c, _ = ls.accept()
            k += 1
            serve(c, k)
    ls.close()
    say("hostile server: %d connections" % k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
