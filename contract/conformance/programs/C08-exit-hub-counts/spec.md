# C08: Every kind of actor end reaches the exit hub with its reason

**Requirements exercised:** A2.1, A5.2

## Program

Start four actors and one killer. One actor ends itself normally (`stop_self(:normal)`), one divides by zero, one fails itself with
an explicit reason atom (`fail_self`), and one is ended by the killer (`kill_abnormal`). Wait until the reports have arrived, then ask the exit hub for
its summary and print it. The counts are: total 4, normal 1, language 1, memory 0, explicit 2 (the explicit reason, and the kill), foreign fault 0.

## Expected output

After the filter in the kit README (lines the runtime itself writes are dropped), standard output is exactly:

```
hub total=4 normal=1 language=1 memory=0 explicit=2 ffault=0
```

and the exit status is 0.

The line matching `^highest id=` is printed by the exit hub and varies with how many actors the program started; the runner ignores it.

## Reference lowering

- `trials/a02_exit_listener/listener_collects.silica`: unsupervised actors, the listener and the hub.
