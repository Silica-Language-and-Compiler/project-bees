# The lowering-choices file

The contract leaves some decisions to the compiler, because the language it compiles decides them. A compiler (or its
generator) writes a **lowering-choices file** that records each decision, so a person can review what was chosen
without reading the compiler. `tools/check_lowering_choices.py` checks the file against the format below. A file that
passes is complete and well formed; whether the choices are right is for the reviewer and for the conformance programs.

## Format

A line-oriented text file. `#` starts a comment; blank lines are ignored. Names and values never contain spaces.

```
lowering-choices 1
target-contract <token>
compiler <name> <version>
<requirement id> <choice> [key=value ...] [-- note]
```

- The first line is `lowering-choices 1`, the format version.
- `target-contract` names the contract version the compiler targets (A1.4 leaves the version scheme open; use the token the contract's
  header gives, for example `draft-2026-11-04`).
- `compiler` gives your compiler's name and version, one token each.
- Then **one entry for each row of the table below, exactly once, in any order.** An entry starts with the requirement
  id from the guide, then one of the listed choices, then the keys that choice takes, then an optional note after ` -- `.
- `other` and `not-applicable` need a note that says what was done or why the entry does not apply to your language.
- A key marked `?` is optional. A key not listed for the choice is an error. Integers are non-negative and decimal.

## Entries

| Id | What is decided | Choices (keys) |
| --- | --- | --- |
| A3.2 | Stack reserve for spawned actors | `lowered` (`reserve=<bytes>`, `release=<policy>`), `default` (`release=<policy>`). Policies: `release_on_return`, `keep_last_message`, `track_recent_peak`, `release_when_idle`, `keep_high_water`. |
| A3.3 | Suspension points: code that waits in the middle of a function | `phase-field`, `continuation-table`, `other`, `not-applicable` |
| A3.4 | Yield points in long computations | `back-edge`, `budget-counter` (`budget?=<int>`), `none`, `other` |
| A4.2 | Child-id scheme and supervisor tree | `single-pool` (`pool-size=<int>`), `pool-tree` (`fanout=<int>`, `leaf-size=<int>`), `other` |
| A4.3 | Supervisor shape | `one-per-shape`, `uniform-shape`, `other` |
| A4.4 | Restart policy and strategy | `chosen` (`restart=permanent\|transient\|temporary`, `strategy=one_for_one\|one_for_all\|rest_for_one`) |
| A5.1 | Recoverable-error constructs | `result-values`, `result-variants`, `mixed`, `rejected`, `not-applicable` |
| A5.4 | A send to a dead recipient | `proxy`, `liveness-check`, `accept-sender-death`, `not-applicable`, `other` |
| A5.5 | Links and exit requests between actors | `silica-link`, `supervisor-request`, `not-supported`, `other` |
| A6.8 | Byte-level and bit-level operations | `lookup-tables`, `not-supported`, `other` |
| A7.1 | Calls by name and through function values | `module-table`, `own-dispatch`, `not-applicable` |

What the choices mean:

- **A3.3.** `phase-field`: the paused computation is a phase number (and saved values) in the actor state, and the code after
  each suspension is its own function. `continuation-table`: the compiler keeps continuations in a table in the state.
- **A3.4.** `back-edge`: a yield point at each loop back-edge. `budget-counter`: a counter of work done in this dispatch,
  checked at yield points. `none`: the compiler never lets a computation run longer than one dispatch (state it in the note
  if the language guarantees it).
- **A4.2.** `single-pool`: one supervisor with a generated pool of `pool-size` ids. `pool-tree`: the scheme of A4.2, a top
  supervisor whose children are `fanout` leaf supervisors with `leaf-size` ids each.
- **A4.3.** `one-per-shape`: one supervisor for each child state-and-behaviour type. `uniform-shape`: all actors the compiler
  produces have one shape, so one supervisor type serves.
- **A5.1.** `result-values`: the language's fallible operations are written to return a result the program tests.
  `result-variants`: the compiler rewrites a construct that catches one failure into BEES's result-returning variant.
  `mixed`: both. `rejected`: constructs that cannot be lowered either way are rejected at compile time (the usual case; say so
  in a note when the choice above is `mixed` and some constructs are rejected).
- **A5.4.** `proxy`: a helper actor takes the failure of a send to a dead recipient. `liveness-check`: the sender checks first
  (racy). `accept-sender-death`: the language's send is Silica's `cast`, and the sender dies with `actor_not_found`; say so in
  the documentation the compiler's users read (A9).
- **A5.5.** `silica-link`: Silica's `link`. `supervisor-request`: exit requests are requests to the target's supervisor.
- **A6.8.** `lookup-tables`: generated lookups and same-type arithmetic (the only route today).
- **A7.1.** `module-table`: the table `bees_config` generates (A7). `own-dispatch`: a table the compiler writes itself.

## Using the checker

```
tools/check_lowering_choices.py FILE...        exit 0 when every file is valid; errors as FILE:LINE: message
tools/check_lowering_choices.py --template     a valid file with every entry set to its first choice
tools/check_lowering_choices.py --requirements the table above, as the checker knows it
```

A generator can import the module and call `check(text)`, which returns a list of `(line number, message)` pairs. The
tests are `tools/test_check_lowering_choices.py`; `lowering-choices.example` is a valid file.

When the contract adds or changes a choice, the version on the first line changes and the checker changes with it.
