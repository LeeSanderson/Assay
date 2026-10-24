# Instructions

Your task is to build a stopwatch to keep precise track of lap times.

The stopwatch uses four commands (start, stop, lap, and reset) to keep track of:

1. The current lap's tracked time
2. Previously recorded lap times

What commands can be used depends on which state the stopwatch is in:

1. Ready: initial state
2. Running: tracking time
3. Stopped: not tracking time

| Command | Begin state | End state | Effect                                                   |
| ------- | ----------- | --------- | -------------------------------------------------------- |
| Start   | Ready       | Running   | Start tracking time                                      |
| Start   | Stopped     | Running   | Resume tracking time                                     |
| Stop    | Running     | Stopped   | Stop tracking time                                       |
| Lap     | Running     | Running   | Add current lap to previous laps, then reset current lap |
| Reset   | Stopped     | Ready     | Reset current lap and clear previous laps                |

## Interface

Times are strings in the form `"HH:MM:SS"`, with two digits for each of hours, minutes and seconds (for example `"00:00:00"`, `"00:01:38"` or `"14:08:30"`).

- `NewSplitSecondStopwatch()` returns a stopwatch in the ready state.
- `State()` returns `"ready"`, `"running"` or `"stopped"`.
- `CurrentLap()` returns the current lap's tracked time as `"HH:MM:SS"`. It is `"00:00:00"` for a new stopwatch, after a lap and after a reset.
- `Total()` returns the total tracked time as `"HH:MM:SS"`: the previous laps plus the current lap.
- `PreviousLaps()` returns a `[]string` of the recorded lap times, each as `"HH:MM:SS"`, oldest first.
- `AdvanceTime(by string)` moves time forward by `by`, given as `"HH:MM:SS"`. The time counts toward the current lap and the total only while the stopwatch is running.

`Start`, `Stop`, `Lap` and `Reset` return `nil` when the command is allowed in the current state. Otherwise they return an error whose `Error()` text is exactly:

| Command | Not allowed when       | Error text                                       |
| ------- | ---------------------- | ------------------------------------------------ |
| Start   | Running                | `"cannot start an already running stopwatch"`    |
| Stop    | Ready or Stopped       | `"cannot stop a stopwatch that is not running"`  |
| Lap     | Ready or Stopped       | `"cannot lap a stopwatch that is not running"`   |
| Reset   | Ready or Running       | `"cannot reset a stopwatch that is not stopped"` |

Implement the solution in `split_second_stopwatch.go`. Keep the exported names and signatures as they are. Tests that you cannot see will check your solution.
