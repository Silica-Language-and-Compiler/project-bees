# A deliverer (bees_peers@dlv_chain) is an actor without a supervisor that ends normally (stop_self(:normal)) after each
# delivery, and the runtime reports each such end from that actor's thread, so where the report lands varies. Deleted: the
# reports whose reason is :normal and the runtime's root-actor notice. Any other report stays and is compared.
/^\[silica\] root actor exited \(no supervisor\)$/d
/^=== Silica Actor Failure ===$/,/^=== End Silica Actor Failure ===$/{
	H
	/^=== End Silica Actor Failure ===$/!d
	s/.*//
	x
	/reason: +:normal/d
	s/^\n//
}
/^$/d
