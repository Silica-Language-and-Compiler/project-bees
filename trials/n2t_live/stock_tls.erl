%% N2T live trial: the short scenarios of the stock Erlang side (the long ones, stock_dials and bees_dials, are
%% trials/n2_live/stock_driver.erl's, unchanged, run here over -proto_dist inet_tls). Every printed line starts with "stock:".
-module(stock_tls).
-export([ping_cast/1, refused_ping/1, waits/1, late_peer/1]).

out(Fmt, Args) -> io:format(Fmt ++ "~n", Args).

%% The stock node dials BEES (found through EPMD) by pinging it, casts to its local name and receives BEES's answer, which
%% carries a BEES pid: a message each way over one link.
ping_cast(Bees) ->
    Main = self(),
    out("stock: ping ~s -> ~p", [Bees, net_adm:ping(Bees)]),
    out("stock: the link's protocol is ~p", [protocol(Bees)]),
    timer:sleep(1000),          % let the kernel's own nodeup traffic (rex, global) pass first, so the audit order is stable
    register(outbox, spawn(fun() -> receive M -> Main ! {outbox, M} end end)),
    {inbox, Bees} ! #{op => hello, n => 1},
    out("stock: sent {inbox, BEES} ! #{op => hello, n => 1}", []),
    receive
        {outbox, {P, #{op := Op, n := N}}} when is_pid(P) ->
            out("stock: outbox got {Pid, #{op => ~p, n => ~p}}; node(Pid) is BEES: ~p", [Op, N, node(P) =:= Bees]);
        Other ->
            out("stock: outbox got ~p", [Other])
    after 10000 ->
        out("stock: outbox got nothing", [])
    end,
    out("stock: done", []).

%% what net_kernel says the link to Node runs over (tls for -proto_dist inet_tls, tcp otherwise)
protocol(Node) ->
    case net_kernel:nodes_info() of
        {ok, L} ->
            case lists:keyfind(Node, 1, L) of
                {_, Info} ->
                    case lists:keyfind(address, 1, Info) of
                        {address, A} when is_tuple(A) -> element(4, A);   % #net_address.protocol
                        _ -> unknown
                    end;
                false -> not_connected
            end;
        _ -> unknown
    end.

%% A stock node that BEES must refuse (its TLS settings, its certificate or its cookie are wrong) pings BEES: pang.
refused_ping(Bees) ->
    out("stock: ping ~s -> ~p", [Bees, net_adm:ping(Bees)]),
    out("stock: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    out("stock: done", []).

%% A stock node that BEES dials and that must not end up connected: it only waits.
waits(Bees) ->
    out("stock: waiting", []),
    timer:sleep(6000),
    out("stock: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    out("stock: done", []).

%% F1-1 (development-plan/spikes/F1-fuzzer.md): the stock node starts AFTER BEES's first EPMD lookup failed (the driver waits for
%% that audit line). It registers with EPMD and waits for BEES's redial to connect (nodeup), then casts to BEES's outbox over the
%% new link and checks the link runs over TLS.
late_peer(Bees) ->
    ok = net_kernel:monitor_nodes(true),
    out("stock: registered, waiting for BEES to dial again", []),
    receive
        {nodeup, Bees} -> out("stock: nodeup ~s; the link's protocol is ~p", [Bees, protocol(Bees)])
    after 30000 ->
        out("stock: no nodeup from ~s", [Bees])
    end,
    timer:sleep(1000),          % let the kernel's own nodeup traffic (rex, global) pass first, so the audit order is stable
    {outbox, Bees} ! #{op => inc, n => 42},
    out("stock: sent {outbox, BEES} ! #{op => inc, n => 42}", []),
    timer:sleep(1500),
    out("stock: done", []).
