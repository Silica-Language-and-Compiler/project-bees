# The BEES conformance kit

This kit is how a compiler author, or a generator acting for one, shows that a compiler follows the BEES target
contract (`contract/so-you-want-to-write-a-compiler.md`, section A10). It has two parts:

1. **Reference programs** (`programs/`): eight small programs stated in prose, each with the exact output it
   must produce and a hand-written Silica lowering that is known to pass.
2. **The lowering-choices file** (`lowering-choices.md`): the record of every decision the contract leaves to your
   compiler, with a checker, `tools/check_lowering_choices.py`.

Nothing in the kit depends on the language your compiler reads. Each program is described in words; you write it in
your language, compile it, and compare.

## What a pass means

A compiler **conforms** when, for every program in `programs/`:

- the program, written in the compiler's source language and compiled by it, builds with the Silica compiler together
  with the BEES units, after `bees_config check` has found no symbol literal outside `bees_atoms`;
- it runs to the end and exits with status 0;
- its output, after the filter below, equals the program's `expected.out` line for line;

and the compiler wrote a lowering-choices file that `tools/check_lowering_choices.py` accepts.

The kit tests behaviour, not source text: how you lower a construct is yours to choose, so long as the output is the
same. It does not test performance, other targets (it is verified on Apple Silicon macOS only), or the parts of BEES
that are not built yet.

**The output filter.** Drop lines the runtime writes itself (they begin `[silica]`), the final `exit=N` line (N must
be 0), blank lines, and any line matching an expression in the program's `ignore` file. Compare the rest with
`expected.out`, ignoring the amount of white space inside a line.

## The programs

| Id | Program | Requirements |
| --- | --- | --- |
| C01 | Selective receive in the middle of a function | A3.3, A6.1, A6.9 |
| C02 | Receive with a timeout, and a late timeout that must be ignored | A3.3, A3.4 |
| C03 | A fallible call rewritten to its result-returning form | A5.1, A6.3, A6.4 |
| C04 | Function values and dynamic application | A7.1, A6.1 |
| C05 | Binary matching without type conversion | A6.7, A6.8 |
| C06 | A ring of processes passing a token | A2.1, A2.2, A3.1, A4.1, A4.2 |
| C07 | A supervised worker that crashes is restarted from its initial state | A4.4, A5.2, A5.4, A2.1 |
| C08 | Every kind of actor end reaches the exit hub with its reason | A2.1, A5.2 |

Each directory holds `spec.md` (the program and its expected output), `expected.out` (the golden), optional `ignore`
(filter expressions), `reference` (which trial leaf holds the passing lowering) and `reference.silica`, a symlink to
that lowering. Read the reference to see one way to meet the requirements; it is not the only way.

## How to run the kit

1. Read a program's `spec.md`. Write the program in your language.
2. Compile it with your compiler into a **leaf directory**: a directory with a two-line `Makefile`

   ```
   BEES_ROOT := /path/to/project-bees
   include $(BEES_ROOT)/tools/trial.mk
   ```

   your generated units (one entry unit with `main`, the rest under `lib/`; `lib/` also holds symlinks to the BEES units
   you use, as in `trials/a02_ring/lib`, and your manifests `.atoms`, `.module` and `.pools`). A leaf built this way
   is built by `make -C LEAF build`: it runs `bees_config`, orders the units, compiles and links.
3. Run the check:

   ```
   tools/conformance.py run LEAF ENTRY C02
   ```

   `ENTRY` is the entry unit's name without `.silica`. The script builds and runs the leaf and prints `pass` or the
   difference. To check output you captured another way: `tools/conformance.py compare OUTFILE C02`.
4. Write the lowering-choices file and check it: `tools/check_lowering_choices.py FILE`.

A generator should run steps 2 to 4 after every generation and accept a change only if all of them pass.

## Keeping the kit honest

`tools/conformance.py check-kit` runs no program. It reads each reference lowering's recorded golden from its trial
leaf and applies the same filter, so the kit's expected output and the reference lowerings cannot drift apart.
`make -C trials integrate` still builds and runs every reference lowering. `make kit` (from the repository root) runs
`check-kit` and the checker's tests. Change an expected output only together with the reference lowering that
produces it.

**Reference lowerings and where they live.** C01 to C05 are in `trials/s09_reference_lowerings`, C06 and C07 in
`trials/a02_ring`, C08 in `trials/a02_exit_listener`. The reference for C04 spells its dispatch by hand; the generated
module table has its own trial, `trials/a03_module_table`.
