%% bees_codec_fixtures: the bytes stock Erlang writes (term_to_binary/1) for the terms the C1 codec trials compare with
%% (development-plan/spikes/C1-codec-term-coverage.md). Each line printed is `label hex`; the hex strings are pasted into the
%% trial sources as fixtures (trials/c1_codec_sum/main.silica, trials/c1_codec_optref/main.silica), so a trial needs no erl.
%% Regenerate (OTP 28; any directory for the .beam):
%%     erlc -o /tmp tools/bees_codec_fixtures.erl && erl -noshell -pa /tmp -s bees_codec_fixtures print -s init stop
%% A map with atom keys has no stable key order in erl's output (it follows the atom table), so a trial compares bytes only for
%% terms without a map and DECODES the fixture where there is one.
-module(bees_codec_fixtures).
-export([print/0, fixtures/0]).

print() ->
    lists:foreach(fun({Label, Term}) -> io:format("~s ~s~n", [Label, hex(term_to_binary(Term))]) end, fixtures()).

hex(Bin) -> lists:flatten([io_lib:format("~2.16.0b", [B]) || <<B>> <= Bin]).

chain(0) -> none;
chain(N) -> {ok, N, chain(N - 1)}.

fixtures() ->
    [%% sum types (trials/c1_codec_sum)
     {"colour_red", red}, {"colour_green", green}, {"colour_blue", blue},
     {"val_i7", {i, 7}}, {"val_i_neg", {i, -1}}, {"val_i_big", {i, 2147483648}},
     {"val_u_max", {u, 18446744073709551615}}, {"val_n_min", {n, -9223372036854775808}},
     {"val_s_hi", {s, <<"hi">>}}, {"val_s_empty", {s, <<>>}}, {"val_f", {f, 1.5}}, {"val_none", none},
     {"shape_pt", {pt, 3, -4}}, {"shape_rec", #{x => 1, y => <<"a">>}}, {"shape_nil", nil},
     {"item", #{id => 9, st => on, items => [{i, 1}, {s, <<"z">>}, gap]}},
     {"item_empty", #{id => 0, st => off, items => []}},
     {"wrap_some", {wrap, #{k => a, v => {some, 5}}}}, {"wrap_none", {wrap, #{k => b, v => none}}},
     {"ping_atom", ping}, {"ping_tuple", {ping, <<"x">>}},
     %% optional references, recursive tuples (trials/c1_codec_optref)
     {"chain1", {ok, 1, none}}, {"chain3", {ok, 5, {ok, 3, {ok, 4, none}}}},
     {"cons2", {cons, 1, {cons, 2, none}}},
     {"tagged", {chain, #{id => 7, head => {1, <<"a">>, {2, <<"b">>, none}}}}},
     {"holder", #{id => 7, head => {1, <<"a">>, {2, <<"b">>, none}}}},
     {"chain60", chain(60)}, {"chain65", chain(65)}, {"chain66", chain(66)}].
