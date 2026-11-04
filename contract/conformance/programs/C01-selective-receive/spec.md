# C01: Selective receive in the middle of a function

**Requirements exercised:** A3.3, A6.1, A6.9

## Program

Two processes. `pong` loops: it receives a request `{ping, From, N}` and answers `From` with `{pong, N}`.
`ping` is given the pid of `pong`. It sends two requests, `{ping, self, 1}` then `{ping, self, 2}`, and then
waits for the answer to the SECOND request first and the answer to the first request second:

    receive {pong, 2} -> print "pong 2" end,
    receive {pong, 1} -> print "pong 1" end,
    print "done"

The answer `{pong, 1}` reaches `ping` before `{pong, 2}`, while `ping` is still waiting for 2. A message that
matches no clause of the receive that is waiting must be kept, in arrival order, and offered to the next receive
before any new message is.

## Expected output

After the filter in the kit README (lines the runtime itself writes are dropped), standard output is exactly:

```
pong 2
pong 1
done
```

and the exit status is 0.

## Reference lowering

- `trials/s09_reference_lowerings/ping_pong_selective_receive.silica`: hand lowering with the BEES save queue (bees_recv).
