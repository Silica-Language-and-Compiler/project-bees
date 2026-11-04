# C03: A fallible call rewritten to its result-returning form

**Requirements exercised:** A5.1, A6.3, A6.4

## Program

`to_atom(S)` converts a text to a symbol only if the program already holds that symbol, and answers `undefined`
otherwise:

    to_atom(S) -> try list_to_existing_atom(S) catch error:badarg -> undefined end.

The program prints the text of `to_atom("hello")`, a space, whether it equals the symbol `hello`, and a newline; then the text of
`to_atom("no_such_atom")` and a newline. The first text is a symbol the program contains and the second is not. Nothing is caught
inside the process: a compiler that cannot rewrite the construct into a form that returns a result must reject the program at compile time (A5.1).

## Expected output

After the filter in the kit README (lines the runtime itself writes are dropped), standard output is exactly:

```
hello true
undefined
```

and the exit status is 0.

## Reference lowering

- `trials/s09_reference_lowerings/try_catch_rewrite.silica`: hand lowering to bees_atoms@from_spelling, which answers found: true or false.
