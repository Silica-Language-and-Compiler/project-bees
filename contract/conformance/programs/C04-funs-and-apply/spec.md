# C04: Function values and dynamic application

**Requirements exercised:** A7.1, A6.1

## Program

A function `twice(F, X)` returns `F(F(X))`. The program builds the function value `fun(N) -> N + 3 end`, applies
`twice` to it and 10, and prints the result; it prints a space; it then calls `twice` by name through dynamic application
(`apply(Module, twice, [fun(N) -> N * 2 end, 5])`, the module and function names being values at run time) and prints
that result and a newline.

## Expected output

After the filter in the kit README (lines the runtime itself writes are dropped), standard output is exactly:

```
16 20
```

and the exit status is 0.

## Reference lowering

- `trials/s09_reference_lowerings/funs_and_apply.silica`: hand-written dispatch in one unit.

The generated module table that a compiler can use for `apply` and for function values (`bees_modules`, built by `bees_config` from `.module` manifests) has its own trial, `trials/a03_module_table`; its output is different and is not part of this program's check.
