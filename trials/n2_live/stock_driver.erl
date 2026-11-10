%% N2: the stock Erlang side of trials/n2_live (OTP 28, the installed erl; D14 names OTP 29, this test is against 28).
%% Started by tools/n2_live.py as `erl -sname <name>@localhost -setcookie <cookie> -kernel net_ticktime 8
%% -kernel inet_dist_use_interface {127,0,0,1}` with ERL_EPMD_PORT pointing at a private EPMD bound to 127.0.0.1.
%% Every line it prints is deterministic (no pids, ports or times) except those starting "evidence:", which the driver keeps
%% in the raw file and normalises in the golden. Results of helper processes are sent to the main process and printed in a
%% fixed order.
-module(stock_driver).
-export([stock_dials/1, bees_dials/1, wrong_ping/1, wrong_listen/1, unlisted_ping/1]).

out(Fmt, Args) -> io:format(Fmt ++ "~n", Args).

wait_msg(Timeout) ->
    receive M -> M after Timeout -> timeout end.

%% A BEES pid that BEES did not hand out: same node and creation as BEES's own pids, id 99.
foreign_pid(Node, Creation) ->
    N = atom_to_binary(Node),
    binary_to_term(<<131, 88, 119, (byte_size(N)), N/binary, 99:32, 0:32, Creation:32>>).

%% Scenario stock_dials: the stock node dials BEES (found through EPMD) by pinging it, sends to its local name, receives a
%% message carrying a BEES pid, answers through that pid, links, unlinks and monitors it, keeps the link 26 s (3 x 8 s ticks),
%% then asks the driver to kill BEES and watches nodedown, the linked process and the monitor.
stock_dials(Bees) ->
    Main = self(),
    erlang:monitor_node(Bees, true),
    out("stock: ping ~s -> ~p", [Bees, net_adm:ping(Bees)]),
    out("stock: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    timer:sleep(1000),          % let the kernel's own nodeup traffic (rex, global) pass first, so the audit order is stable
    register(outbox, spawn(fun() -> receive M -> Main ! {outbox, M} end end)),
    {inbox, Bees} ! #{op => hello, n => 1},
    out("stock: sent {inbox, BEES} ! #{op => hello, n => 1}", []),
    Pid = case wait_msg(10000) of
              {outbox, {P, #{op := Op, n := N}}} when is_pid(P) ->
                  out("stock: outbox got {Pid, #{op => ~p, n => ~p}}; node(Pid) is BEES: ~p", [Op, N, node(P) =:= Bees]),
                  P;
              Other ->
                  out("stock: outbox got ~p", [Other]),
                  halt(1)
          end,
    Pid ! #{op => viapid, n => 3},
    out("stock: sent Pid ! #{op => viapid, n => 3}", []),
    timer:sleep(500),           % BEES prints the delivery before the next frame's audit line
    <<131, 88, Rest/binary>> = term_to_binary(Pid),
    Creation = binary:decode_unsigned(binary:part(Rest, byte_size(Rest) - 4, 4)),
    Foreign = foreign_pid(Bees, Creation),
    Foreign ! #{op => viapid, n => 4},
    out("stock: sent a BEES pid that BEES did not hand out a message (dropped by BEES)", []),
    %% linker A: link, unlink, monitor (the monitor request is dropped by BEES, D21)
    spawn(fun() ->
                  true = link(Pid), true = unlink(Pid),
                  Ref = monitor(process, Pid),
                  Main ! {a, monitoring},
                  receive {'DOWN', Ref, process, _, R} -> Main ! {a, down, R} end
          end),
    %% linker C: link to the pid BEES did not hand out: BEES answers EXIT noproc
    spawn(fun() ->
                  process_flag(trap_exit, true), link(Foreign),
                  receive {'EXIT', Foreign, R} -> Main ! {c, R} after 5000 -> Main ! {c, no_exit} end
          end),
    %% linker B: stays linked, trapping exits, until BEES dies
    spawn(fun() ->
                  process_flag(trap_exit, true), link(Pid), Main ! {b, linked},
                  receive {'EXIT', Pid, R} -> Main ! {b, exit, R} end
          end),
    receive {a, monitoring} -> out("stock: linker A linked, unlinked and monitors the BEES pid", []) after 5000 -> out("stock: linker A did not report", []) end,
    receive {c, R1} -> out("stock: link to a pid BEES did not hand out ended with ~p", [R1]) end,
    receive {b, linked} -> out("stock: linker B is linked to the BEES pid", []) after 5000 -> out("stock: linker B did not report", []) end,
    timer:sleep(1000),
    out("stock: after link, unlink, monitor: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    out("stock: idle 26 s (more than 3 x net_ticktime 8 s)", []),
    timer:sleep(26000),
    out("stock: after 26 s idle: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    T0 = erlang:monotonic_time(millisecond),
    out("stock: KILL NOW", []),
    receive {nodedown, Bees} ->
            Ms = erlang:monotonic_time(millisecond) - T0,
            out("stock: nodedown seen within net_ticktime (8 s): ~p", [Ms < 8000]),
            out("evidence: nodedown after ~p ms", [Ms])
    after 20000 -> out("stock: no nodedown within 20 s", [])
    end,
    receive {b, exit, RB} -> out("stock: linker B exited with ~p", [RB]) after 5000 -> out("stock: linker B got no exit", []) end,
    receive {a, down, RA} -> out("stock: linker A's monitor fired with ~p", [RA]) after 5000 -> out("stock: linker A's monitor did not fire", []) end,
    out("stock: done", []).

%% Scenario bees_dials: the stock node waits in a registered process `inbox`; BEES looks it up in EPMD and dials it, and casts
%% to inbox; the stock node answers with {outbox, BEES} ! Term over the same connection.
bees_dials(Bees) ->
    Main = self(),
    register(inbox, spawn(fun() -> receive M -> Main ! {inbox, M} end end)),
    out("stock: waiting in registered process inbox", []),
    case wait_msg(30000) of
        {inbox, #{op := Op, n := N}} -> out("stock: inbox got #{op => ~p, n => ~p}", [Op, N]);
        Other -> out("stock: inbox got ~p", [Other])
    end,
    out("stock: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    {outbox, Bees} ! #{op => inc, n => 42},
    out("stock: sent {outbox, BEES} ! #{op => inc, n => 42}", []),
    timer:sleep(2000),
    out("stock: done", []).

%% Scenario wrong_ping: a stock node with another cookie pings BEES: BEES refuses its challenge reply; ping answers pang.
wrong_ping(Bees) ->
    out("stock: ping ~s with another cookie -> ~p", [Bees, net_adm:ping(Bees)]),
    out("stock: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    out("stock: done", []).

%% Scenario wrong_listen: a stock node with another cookie waits; BEES dials it; the stock node refuses BEES's challenge
%% reply (its kernel logs it, the driver keeps that line).
wrong_listen(Bees) ->
    out("stock: waiting with another cookie", []),
    timer:sleep(6000),
    out("stock: nodes() lists BEES: ~p", [lists:member(Bees, nodes())]),
    out("stock: done", []).

%% Scenario unlisted: a stock node that BEES's manifest does not list pings BEES: BEES answers not_allowed; ping answers pang.
unlisted_ping(Bees) ->
    out("stock: ping ~s from a node BEES does not list -> ~p", [Bees, net_adm:ping(Bees)]),
    out("stock: done", []).
