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

The `SplitSecondStopwatch` class has these getters:

- `state`: one of the strings `"ready"`, `"running"` or `"stopped"`.
- `currentLap`: the current lap's time as an `"HH:MM:SS"` string, with two digits in each part (for example `"00:00:00"` or `"01:23:45"`).
- `total`: the total time, in the same `"HH:MM:SS"` format.
- `previousLaps`: an array of the previous lap times, each in the same `"HH:MM:SS"` format, oldest first. It is `[]` when there are no previous laps.

`advanceTime(duration)` takes the time that passes as an `"HH:MM:SS"` string (for example `"00:00:05"`).

A command that is not allowed in the current state throws an `Error` with this message:

- `start` when running: `"cannot start an already running stopwatch"`
- `stop` when not running: `"cannot stop a stopwatch that is not running"`
- `lap` when not running: `"cannot lap a stopwatch that is not running"`
- `reset` when not stopped: `"cannot reset a stopwatch that is not stopped"`

Implement the solution in `split-second-stopwatch.ts`. Keep the exported names and signatures as they are. Tests that you cannot see will check your solution.
