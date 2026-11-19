%% C1 codec coverage: the stock Erlang side of trials/c1_codec_live (OTP 27 or 28, the installed erl). Started by
%% tools/bees_codec_live.py as `erl -sname stock@localhost -setcookie <cookie> -kernel net_ticktime 8
%% -kernel inet_dist_use_interface {127,0,0,1}` with ERL_EPMD_PORT pointing at the trial's private EPMD on 127.0.0.1.
%% Every line it prints starts "stock:" and is deterministic: no pid, reference, port or time is printed (terms that hold
%% one are described, not shown), and maps are printed with their keys in order (~0kp). Each registered process hands what it
%% receives to the main process, which prints in the order of arrival; BEES sends its next message only after the previous one
%% came back, and this side sends its next step only after BEES acknowledged the previous one, so the order is the protocol's.
%% Sets are built with sets:from_list(L, [{version, 2}]): the map form BEES carries (ruling Q4), which sets:from_list/1
%% returns by default only from OTP 28; on OTP 27 sets:from_list/1 gives the version 1 record, which BEES refuses (phase 2
%% sends one on purpose), so the trial checks the ruled form on both versions.
-module(codec_driver).
-export([kinds/1]).

out(Fmt, Args) -> io:format(Fmt ++ "~n", Args).

hex(Bin) -> lists:flatten([io_lib:format("~2.16.0b", [X]) || <<X>> <= Bin]).

relay(Name, Main) ->
    receive M -> Main ! {Name, M}, relay(Name, Main) end.

%% {ok,N,{ok,N-1,...{ok,1,none}}}: the recursive tuple of the manifest's (atom, int64, ref?(L, normal, rec))
chain(1) -> {ok, 1, none};
chain(N) -> {ok, N, chain(N - 1)}.

%% a term as text on one line, map keys in order; the buffer's bytes as numbers (~p would print them as Latin-1 text)
shown(pkt, T) -> io_lib:format("~kw", [T]);
shown(_, T) -> io_lib:format("~0kp", [T]).

x(Name) -> list_to_atom(atom_to_list(Name) ++ "x").

%% Phase 1: what BEES sends, in order: {the registered name it arrives at, the term, whether term_to_binary's bytes are
%% canonical (no map with atom keys: their order follows the atom table)}.
expected() ->
    [{val, {i, 7}, true},
     {val, {s, <<"hi">>}, true},
     {val, {f, 1.5}, true},
     {val, {pt, 3, -4}, true},
     {val, #{x => 1, y => <<"rec">>}, false},
     {val, none, true},
     {chain, {ok, 3, {ok, 2, {ok, 1, none}}}, true},
     {im, #{1 => <<"a">>, 2 => <<"b">>, 3 => <<"c">>}, true},
     {im, #{9 => <<"after">>}, true},
     {ints, sets:from_list([1, 2, 3], [{version, 2}]), true},
     {ints, sets:from_list([4], [{version, 2}]), true},
     {pkt, #{id => 7, data => <<16#de, 16#ad, 16#be, 16#ef>>, note => <<"n">>}, false},
     {pkt, #{id => 10, data => <<16#de, 16#ad>>, note => <<"after">>}, false},
     {wide, #{a => 1, b => <<"two">>, c => true, d => 4.5, e => wide, f => [1000, 2000]}, false},
     {any, {7, -1234567890123, 1208925819614629174706176, 2.5, hello, zzqx_not_held, <<"bin">>, <<5:3>>, {a, 1},
            [1, 2, 3], [x, y], [a | b], #{1 => one}, []}, true},
     {any, {'after', 1}, true},
     {val, {s, <<"bye">>}, true}].

phase1(_Bees, []) -> ok;
phase1(Bees, [{Name, Exp, Canon} | Rest]) ->
    receive
        {ack, M} ->
            out("stock: an acknowledgement ~0kp where ~w was expected", [M, Name]), halt(1);
        {Got, T} ->
            out("stock: ~w got ~s", [Got, shown(Got, T)]),
            out("stock:   the term expected at ~w (=:=): ~p", [Name, Got =:= Name andalso T =:= Exp]),
            case Got of
                ints -> out("stock:   sets:is_set ~p, sets:to_list sorted ~w", [sets:is_set(T), lists:sort(sets:to_list(T))]);
                _ -> ok
            end,
            case Canon of
                true -> out("stock:   term_to_binary ~s", [hex(term_to_binary(T))]);
                false -> ok
            end,
            {x(Got), Bees} ! T,
            phase1(Bees, Rest)
    after 30000 ->
            out("stock: nothing arrived where ~w was expected", [Name]), halt(1)
    end.

wait_ack(N) ->
    receive
        {ack, #{n := N}} -> out("stock: BEES acknowledged step ~w", [N]);
        Other -> out("stock: ~0kp where the acknowledgement ~w was expected", [Other, N]), halt(1)
    after 30000 ->
            out("stock: no acknowledgement ~w", [N]), halt(1)
    end.

%% Phase 2: terms that do not fit the type of a typed name (BEES must drop each), then one that fits (BEES prints and
%% acknowledges it). Bad and Good are {text, term}.
typed(Bees, Name, Bad, {GoodText, Good}, N) ->
    lists:foreach(fun({Text, Term}) ->
                          {Name, Bees} ! Term,
                          out("stock: sent {~w, BEES} ! ~s (does not fit: BEES drops it)", [Name, Text])
                  end, Bad),
    {Name, Bees} ! Good,
    out("stock: sent {~w, BEES} ! ~s", [Name, GoodText]),
    wait_ack(N).

%% Phase 3: any term to the name whose type is `term`; BEES sends it back; =:= with what was sent.
dynamic(_Bees, _K, []) -> ok;
dynamic(Bees, K, [{Text, Term} | Rest]) ->
    {tany, Bees} ! Term,
    receive
        {tanyx, Echo} -> out("stock: term ~w, ~s: the echo =:= the original: ~p", [K, Text, Echo =:= Term]);
        Other -> out("stock: term ~w: ~0kp where the echo was expected", [K, Other]), halt(1)
    after 30000 ->
            out("stock: term ~w, ~s: no echo", [K, Text]), halt(1)
    end,
    dynamic(Bees, K + 1, Rest).

kinds(Bees) ->
    Main = self(),
    out("stock: ping ~s -> ~p", [Bees, net_adm:ping(Bees)]),
    timer:sleep(1000),          % let the kernel's own nodeup traffic (rex, global) pass first, so the audit order is stable
    [register(N, spawn(fun() -> relay(N, Main) end)) || N <- [val, chain, im, ints, pkt, wide, any, ack, tanyx]],
    out("stock: phase 1: BEES sends each kind to a registered process here; each is printed, compared and sent back", []),
    {kick, Bees} ! #{n => 0},
    phase1(Bees, expected()),
    wait_ack(100),
    out("stock: phase 2: terms that do not fit a typed name of BEES, each followed by one that does", []),
    typed(Bees, rval,
          [{"{zz,1}, a tag the sum does not have", {zz, 1}},
           {"{i,<<\"x\">>}, a binary where the variant holds an integer", {i, <<"x">>}},
           {"{pt,1}, a known tag with another arity", {pt, 1}},
           {"nope, an atom that is no variant", nope}],
          {"{i,42}", {i, 42}}, 1),
    typed(Bees, rchain,
          [{"a chain of 66 cells, deeper than the limit", chain(66)},
           {"{ok,2,{ok,1,nil}}, an atom other than none in the empty slot", {ok, 2, {ok, 1, nil}}}],
          {"a chain of 65 cells", chain(65)}, 2),
    typed(Bees, rim,
          [{"#{1 => 2}, an integer where the value is a binary", #{1 => 2}},
           {"#{a => <<\"x\">>}, an atom where the key is an integer", #{a => <<"x">>}},
           {"[{1,<<\"a\">>}], a list of pairs", [{1, <<"a">>}]}],
          {"#{5 => <<\"five\">>, 6 => <<\"six\">>}", #{5 => <<"five">>, 6 => <<"six">>}}, 3),
    typed(Bees, rints,
          [{"[1,2,3], a list where the set's map is expected", [1, 2, 3]},
           {"#{1 => x}, a map whose value is not []", #{1 => x}},
           {"ordsets:from_list([300,100,200]), a sorted list", ordsets:from_list([300, 100, 200])},
           {"sets:from_list([5,6], [{version,1}]), the record form (sets:from_list/1 before OTP 28)", sets:from_list([5, 6], [{version, 1}])}],
          {"sets:from_list([7,8,9], [{version,2}])", sets:from_list([7, 8, 9], [{version, 2}])}, 4),
    typed(Bees, rpkt,
          [{"data of 17 bytes for a buffer of 16", #{id => 1, data => binary:copy(<<9>>, 17), note => <<"long">>}},
           {"data that is an integer", #{id => 1, data => 5, note => <<"int">>}}],
          {"data of 16 bytes", #{id => 2, data => <<1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16>>, note => <<"full">>}}, 5),
    typed(Bees, rwide,
          [{"the record without its field f", #{a => 1, b => <<"two">>, c => true, d => 4.5, e => wide}},
           {"the record with a seventh field", #{a => 1, b => <<"two">>, c => true, d => 4.5, e => wide, f => [], g => 0}},
           {"the record whose atom field e holds stock, an atom BEES does not have (a typed atom is one of the node's own)",
            #{a => 2, b => <<"erl">>, c => false, d => 2.5, e => stock, f => [1, 2, 300]}}],
          {"#{a => 2, b => <<\"erl\">>, c => false, d => 2.5, e => val, f => [1,2,300]}",
           #{a => 2, b => <<"erl">>, c => false, d => 2.5, e => val, f => [1, 2, 300]}}, 6),
    out("stock: phase 3: arbitrary terms to the name whose type is term; BEES sends each back", []),
    Port = hd(erlang:ports()),
    Local = fun() -> Bees end,
    dynamic(Bees, 0,
            [{"{self(), make_ref(), a port, fun erlang:node/0, a local fun, atom_bees_never_saw_qqzx}",
              {self(), make_ref(), Port, fun erlang:node/0, Local, atom_bees_never_saw_qqzx}},
             {"[1, -1, 2.5, 123456789012345678901234567890, {<<\"bin\">>, <<1:1>>}, #{k => [a|b]}, \"str\", [], [x]]",
              [1, -1, 2.5, 123456789012345678901234567890, {<<"bin">>, <<1:1>>}, #{k => [a | b]}, "str", [], [x]]},
             {"self()", self()},
             {"make_ref()", make_ref()},
             {"#{a pid => [a reference, a reference], fun lists:map/2 => a port}",
              #{self() => [make_ref(), make_ref()], fun lists:map/2 => Port}}]),
    out("stock: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    out("stock: done", []).
