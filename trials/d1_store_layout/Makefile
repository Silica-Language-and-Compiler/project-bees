# D1 (spikes/N0d-store-config.md): the on-medium layout of Silica's hosted (:store) carrier, guarded from both sides. The layout
# is Silica's (transport design 6.8.4, 6.8.9); the configuration packer writes it directly (tools/bees_pack_store.py, D46), so a
# change of it in Silica must fail here.
#
#   dangerous_d1_read    opens "d1.sildat" (16384 bytes, :stop), replays it, reassembles the frames (wireframe :storage),
#                        takes off the record header (wireframe@unrecord) and decodes each value with decode((:etf), ...)
#   dangerous_d1_write   writes the same values through the carrier: encode((:etf), ...), wireframe@record, wireframe@frame
#                        (into "d1w.sildat": two declarations of one build may not claim the same backing, E2415)
#
# cases.py runs the reader on backings the PACKER wrote (whole, damaged, of another size, held by another process, absent) and
# compares the backing the writer leaves with the packer's image byte for byte. Run by tools/bees_pack_trial.py.
BEES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
include $(BEES_ROOT)/tools/bees_pack_trial.mk
