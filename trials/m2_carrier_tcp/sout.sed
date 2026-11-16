# The carrier (spawned without a supervisor) stops at the link's end, and two things are written from its thread while the
# owner prints its last lines, so where they land varies: the runtime's "root actor exited" notice, and the carrier's
# normal-exit report. Both are deleted; a report whose reason is not :normal is kept and still checked.
/^\[silica\] root actor exited \(no supervisor\)$/d
/^=== Silica Actor Failure ===$/,/^=== End Silica Actor Failure ===$/{
	H
	/^=== End Silica Actor Failure ===$/!d
	s/.*//
	x
	/reason: +:normal/d
	s/^\n//
}
