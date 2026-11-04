# C02: Receive with a timeout, and a late timeout that must be ignored

**Requirements exercised:** A3.3, A3.4

## Program

One process runs three waits in a row, each of the form `receive ping -> print "got ping" after T -> print "timed out" end`:

- wait 1: T = 40 ms. A `ping` arrives 5 ms after the program starts. Print `got ping`.
- wait 2: T = 300 ms. A `ping` arrives 100 ms after wait 2 began. Print `got ping`.
- wait 3: T = 60 ms. No `ping` is sent. Print `timed out`, then end the program with status 0.

The process may not cancel wait 1's timeout, and even when it does not, that timeout fires (at about 40 ms) while wait 2 is pending
and must not end wait 2. A timeout belongs to the wait that armed it. Use Silica's own timers: there is no BEES
timer unit, and a remaining-time query is the compiler's own bookkeeping, not part of this program.

## Expected output

After the filter in the kit README (lines the runtime itself writes are dropped), standard output is exactly:

```
got ping
got ping
timed out
```

and the exit status is 0.

## Reference lowering

- `trials/s09_reference_lowerings/receive_after.silica`: hand lowering: a timeout message carrying the wait's number, send_after, cancel_timer.
