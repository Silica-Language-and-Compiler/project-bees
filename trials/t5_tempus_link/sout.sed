# Actors without a supervisor (assemblers, send actors, connections, links, carriers) end normally when a connection ends,
# and the runtime reports each such end from that actor's thread, so where the report lands varies. Deleted: the reports
# whose reason is :normal, the runtime's root-actor notice, and the carrier's own report of a lost link (a write to a peer
# that had just closed: whether the write or the notice of the close comes first is a race; the connection's audit line
# closed_by_peer is there either way). Any other report stays and is compared.
/^\[silica\] root actor exited \(no supervisor\)$/d
/^=== Silica Actor Failure ===$/,/^=== End Silica Actor Failure ===$/{
	H
	/^=== End Silica Actor Failure ===$/!d
	s/.*//
	x
	/reason: +:normal/d
	/reason: +\(:explicit, :link_lost\)\n.*dangerous_tcp_carrier_carrier/d
	s/^\n//
}
# The side whose peer closed learns of it at whichever step it had reached (and before or after it read the peer's advert)
s/^(\[tempus audit\] closed_by_peer) peer=[^ ]+ stage [a-z]+/\1 peer=(any) stage (any)/
/^$/d
