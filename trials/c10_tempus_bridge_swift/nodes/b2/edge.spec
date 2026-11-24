# the bridge's per-type permission specs (tools/bees_tempus_gen.py spec): what a peer of each type may call. A type with no
# line may call nothing (design 17.4: none by default). demo:secret/0 is named by no line: the trial's unpermitted request.
type tempus_edge [{demo, [{add, 2}, {crash, 1}, {note, 1}, {onward, 2}, {bad, 0}, {hold, 1}, {release, 0}, {slow, 1}]}]
