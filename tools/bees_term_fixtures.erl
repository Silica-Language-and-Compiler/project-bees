%% Fixtures for trials/c1_codec_term and tools/test_bees_term_etf.py (C1, dynamic terms): the bytes stock Erlang writes
%% (term_to_binary/1, OTP 28) for a list of terms, one "label hex" line each.
%%
%%   escript tools/bees_term_fixtures.erl            every fixture that is the same in every run
%%   escript tools/bees_term_fixtures.erl varying    a pid, a reference, a port and a local fun as this run writes them
%%
%% The trial embeds the hex (trials/c1_codec_term/main.silica); the test asks this file again and compares. A map of two
%% or more atom keys is written in the order of the atoms' indices, which differs between runs, so the test compares
%% those after decoding. The "varying" terms were captured once and are embedded as fixed hex.
-module(bees_term_fixtures).
-export([main/1, fixtures/0, varying/0]).
-mode(compile).

main(["varying"]) -> print(varying());
main(_) -> print(fixtures()).

print(L) ->
    lists:foreach(fun({Label, Term}) ->
        io:format("~s ~s~n", [Label, hex(term_to_binary(Term))]) end, L).

hex(Bin) -> lists:flatten([io_lib:format("~2.16.0b", [B]) || <<B>> <= Bin]).

fixtures() ->
    [{"int_0", 0}, {"int_255", 255}, {"int_256", 256}, {"int_neg1", -1},
     {"int_i32max", 2147483647}, {"int_i32min", -2147483648},
     {"int_i32max1", 2147483648}, {"int_i32min1", -2147483649},
     {"int_i64max", 9223372036854775807}, {"int_i64min", -9223372036854775808},
     {"int_i64max1", 9223372036854775808}, {"int_i64min1", -9223372036854775809},
     {"int_2p64", 1 bsl 64},
     {"big_2048", (1 bsl 2047) + 12345}, {"big_2048_neg", -((1 bsl 2047) + 12345)},
     {"float_1_5", 1.5}, {"float_neg0", -0.0}, {"float_0", 0.0}, {"float_big", 1.0e300}, {"float_pi", math:pi()},
     {"atom_ok", ok}, {"atom_empty", ''}, {"atom_utf8", list_to_atom([104, 233, 108, 108, 111, 8594])},
     {"atom_255", list_to_atom(lists:duplicate(255, $x))},
     {"atom_255_utf8", list_to_atom(lists:duplicate(255, 233))},
     {"bin_empty", <<>>}, {"bin_abc", <<"abc">>}, {"bin_bytes", <<0, 255, 1, 2>>},
     {"bits_3", <<5:3>>}, {"bits_12", <<1, 2, 3:4>>},
     {"tuple_0", {}}, {"tuple_3", {a, 1, <<"x">>}}, {"tuple_300", list_to_tuple(lists:seq(1, 300))},
     {"nil", []}, {"string", "abc"},
     {"list_mixed", [1, a, <<"b">>, {c}, 2.5, [], "s"]},
     {"improper", [1 | 2]}, {"improper2", [a, b | c]},
     {"list_big_ints", [256, 1000, 65536, -1]}, {"list_char_256", [104, 256]},
     {"map_0", #{}}, {"map_1", #{a => 1}}, {"map_atoms", #{a => 1, b => 2}},
     {"map_ints", #{1 => a, 2 => b, 3 => c}},
     {"map_1_and_1_0", #{1 => a, 1.0 => b}},
     {"map_nested", #{k => #{1 => [#{}]}, <<"b">> => {#{}}}},
     {"set", sets:from_list([3, 1, 2])},
     {"export_fun", fun lists:map/2},
     {"mixed", mixed()}].

mixed() ->
    {call, #{id => 7, args => [1, 2.5, <<"bin">>, "str", [x | y], {}, #{}, <<1:1>>], big => 1 bsl 80},
     -0.0, list_to_atom([252, 110, 239]), [fun erlang:node/0, 70000, -70000]}.

varying() ->
    Port = hd(erlang:ports()),
    [{"fixed_pid", self()}, {"fixed_ref", make_ref()}, {"fixed_port", Port},
     {"fixed_local_fun", {f, fun() -> ok end}},
     {"fixed_all", [self(), {make_ref(), Port}, #{f => fun(X) -> X end}]}].
