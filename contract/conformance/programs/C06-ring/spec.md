# C06: A ring of processes passing a token

**Requirements exercised:** A2.1, A2.2, A3.1, A4.1, A4.2

## Program

Start 8 processes in a ring: process i knows process i+1, and the last knows the first. Give the first process a token
that carries a hop count of 1000. A process that receives the token with a count above 0 passes it to its neighbour with the
count reduced by 1; the process that receives it with count 0 prints `ring 8 nodes, 1000 hops, done` and ends the program with status 0.
Every process is supervised, and the supervisor holds all 8 at once, so the program needs 8 distinct child ids.

## Expected output

After the filter in the kit README (lines the runtime itself writes are dropped), standard output is exactly:

```
ring 8 nodes, 1000 hops, done
```

and the exit status is 0.

## Reference lowering

- `trials/a02_ring/ring.silica`: root supervisor, ids from a generated pool (bees_ids).
