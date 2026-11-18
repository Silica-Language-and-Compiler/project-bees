# Each check's verifier actor ends itself when it has answered (stop_self(:normal)); it has no supervisor in this trial, so
# the runtime reports that end on stderr, and where the report lands among the driver's lines varies with scheduling. The
# race decides only where these lines appear, never what the driver prints. Removed: exactly the report of a :normal end
# whose call stack is the verifier's behaviour, and the runtime's root-actor line; any other report stays in the output.
/^=== Silica Actor Failure ===$/{
:a
N
/=== End Silica Actor Failure ===$/!ba
/reason: +:normal\n.*dangerous_bees_tempus_verify_tver/d
}
/^\[silica\] root actor exited \(no supervisor\)$/d
/^$/d
