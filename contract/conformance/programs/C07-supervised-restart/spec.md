# C07: A supervised worker that crashes is restarted from its initial state

**Requirements exercised:** A4.4, A5.2, A5.4, A2.1

## Program

A supervisor holds one permanent worker, reachable by name. The worker's state starts at 100; a request with a value N
other than 0 adds N to the state and answers the new state; a request with 0 divides by zero and so ends the worker.

1. A request with 1 is answered: print `101`.
2. A helper process sends the request 0 and so is waiting for an answer when the worker dies. The helper fails with it. The
   supervisor restarts the worker with state 100 and a new identity.
3. A request with 11 is answered: print `111` (not 112: the old state is gone).
4. The program asks the exit hub for its summary and prints it. Exactly two ends were recorded: the worker's (a division
   by zero, reason `language_error`) and the helper's (an explicit reason, because a call to a dead callee fails its caller).

## Expected output

After the filter in the kit README (lines the runtime itself writes are dropped), standard output is exactly:

```
101
111
hub total=2 normal=0 language=1 memory=0 explicit=1 ffault=0
```

and the exit status is 0.

The line matching `^highest id=` is printed by the exit hub and varies with how many actors the program started; the runner ignores it.

## Reference lowering

- `trials/a02_ring/restart.silica`: root supervisor, listener and hub.
