# C05: Binary matching without type conversion

**Requirements exercised:** A6.7, A6.8

## Program

Given the six bytes 3, 1, 2, 9, 9, 9, match them against the pattern `<<Len:8, Tag:16/big, Rest/binary>>` and
print `Len`, `Tag` and the byte size of `Rest`, separated by spaces, then a newline. `Tag` is the two bytes 1 and 2 read big-endian.

## Expected output

After the filter in the kit README (lines the runtime itself writes are dropped), standard output is exactly:

```
3 258 3
```

and the exit status is 0.

## Reference lowering

- `trials/s09_reference_lowerings/binary_matching.silica`: hand lowering to consecutive byte reads and same-type arithmetic.
