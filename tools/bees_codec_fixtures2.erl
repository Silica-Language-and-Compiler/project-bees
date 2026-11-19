%% bees_codec_fixtures2: the bytes stock Erlang writes (term_to_binary/1) for the terms the C1 codec trials of maps, sets, buf,
%% dynamic-term messages and wide records compare with (development-plan/spikes/C1-codec-term-coverage.md 2.3 to 2.6, 3.5;
%% trials/c1_codec_map, c1_codec_set, c1_codec_buf, c1_codec_termmsg, c1_codec_wide). Each line printed is `label hex`; the hex
%% strings are pasted into the trial sources as fixtures, so a trial needs no erl. Regenerate (OTP 28):
%%     erlc -o /tmp tools/bees_codec_fixtures2.erl && erl -noshell -pa /tmp -s bees_codec_fixtures2 print -s init stop
%% erl's key order in a map is not canonical: sorted for a map of at most 32 keys that are integers (or other non-atom terms),
%% by atom index for atom keys, hash order above 32 keys. A trial compares bytes where BEES's order (the list's) is erl's
%% and DECODES the fixture everywhere.
-module(bees_codec_fixtures2).
-export([print/0, fixtures/0]).

print() ->
    lists:foreach(fun({Label, Term}) -> io:format("~s ~s~n", [Label, hex(term_to_binary(Term))]) end, fixtures()).

hex(Bin) -> lists:flatten([io_lib:format("~2.16.0b", [B]) || <<B>> <= Bin]).

fixtures() ->
    [%% maps (trials/c1_codec_map)
     {"im_empty", #{}},
     {"im_3", #{1 => <<"a">>, 2 => <<"b">>, 3 => <<"c">>}},
     {"im_wide_keys", #{-1 => <<"m">>, 300 => <<"s">>, 4294967296 => <<"big">>}},
     {"im_40", maps:from_list([{K, <<"v">>} || K <- lists:seq(1, 40)])},
     {"sm_2", #{<<"k1">> => #{id => 1, up => true}, <<"k2">> => #{id => 2, up => false}}},
     {"holder", #{id => 7, m => #{1 => im, 2 => sm}, note => <<"n">>}},
     {"cfg", {cfg, #{im => 1, sm => 2}, <<"x">>}},
     {"lists_big", #{1 => [1000, 2000], 2 => []}},
     {"lists_small", #{1 => [1, 2], 2 => []}},
     {"sums", #{1 => {i, 5}, 2 => {s, <<"z">>}, 3 => none}},
     {"nest", #{1 => #{1 => 10, 2 => 20}, 2 => #{}}},
     {"many", [#{1 => 2}, #{}, #{3 => 4, 5 => 6}]},
     {"many_empty", []},
     {"grid", #{{0, 0} => <<"o">>, {0, 1} => <<"n">>, {1, 0} => <<"e">>}},
     %% sets (trials/c1_codec_set): sets:from_list/1, the map form (version 2, the default since OTP 28)
     {"is_empty", sets:from_list([], [{version, 2}])},
     {"is_3", sets:from_list([3, 1, 2], [{version, 2}])},
     {"is_40", sets:from_list(lists:seq(1, 40), [{version, 2}])},
     {"ts_2", sets:from_list([{pt, 1, 2}, {pt, 3, 4}], [{version, 2}])},
     {"strs", sets:from_list([<<"a">>, <<"b">>], [{version, 2}])},
     {"tagset", {tags, 9, sets:from_list([<<"x">>, <<"y">>], [{version, 2}])}},
     {"setmap", #{1 => sets:from_list([1, 2], [{version, 2}]), 2 => sets:from_list([], [{version, 2}])}},
     {"enums", sets:from_list([{i, 1}, none], [{version, 2}])},
     %% buf (trials/c1_codec_buf)
     {"buf_3", <<1, 2, 3>>}, {"buf_empty", <<>>}, {"buf_8", <<0, 255, 128, 127, 1, 2, 3, 4>>}, {"buf_9", <<1, 2, 3, 4, 5, 6, 7, 8, 9>>},
     {"pkt", #{id => 7, data => <<16#de, 16#ad, 16#be, 16#ef>>, note => <<"n">>}},
     {"pair", {<<1, 2>>, <<"mid">>, <<3, 4, 5>>}},
     {"tagged_buf", {blob, 5, <<9, 8, 7>>}},
     {"buf_charlist", [1, 2, 3]},
     %% dynamic-term messages (trials/c1_codec_termmsg)
     {"term_tuple", {hello, 42, <<"bin">>, [1, 2, 3], 1.5}},
     {"term_map", #{1 => a, 2 => [x, {y, -7}]}},
     {"term_big", {123456789012345678901234567890, [a | b]}},
     {"term_unknown_atom", {zzqx_not_held, 1}},
     %% a record of more than four fields (trials/c1_codec_wide)
     {"wide6", #{a => 1, b => <<"two">>, c => true, d => 4.5, e => wide6, f => [1000, 2000]}},
     {"wide5_in", {w, #{p => 1, q => 2, r => 3, s => 4, t => 5}, <<"z">>}},
     {"wide_list", [#{a => 1, b => 2, c => 3, d => 4, e => 5}, #{a => 6, b => 7, c => 8, d => 9, e => 10}]}].
