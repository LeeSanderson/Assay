type State = 'ready' | 'running' | 'stopped'

export class SplitSecondStopwatch {
  private _state: State = 'ready'
  private _currentLap = 0
  private _previousLaps: number[] = []

  constructor() {}

  public get state(): unknown {
    return this._state
  }

  public get currentLap(): unknown {
    return this._currentLap
  }

  public get total(): unknown {
    return this._previousLaps.reduce((sum, lap) => sum + lap, this._currentLap)
  }

  public get previousLaps(): unknown[] {
    return [...this._previousLaps]
  }

  public start(): unknown {
    if (this._state === 'running') {
      throw new Error('Stopwatch is already running')
    }
    this._state = 'running'
    return undefined
  }

  public stop(): unknown {
    if (this._state !== 'running') {
      throw new Error('Stopwatch is not running')
    }
    this._state = 'stopped'
    return undefined
  }

  public lap(): unknown {
    if (this._state !== 'running') {
      throw new Error('Stopwatch is not running')
    }
    this._previousLaps.push(this._currentLap)
    this._currentLap = 0
    return undefined
  }

  public reset(): unknown {
    if (this._state !== 'stopped') {
      throw new Error('Stopwatch must be stopped to reset')
    }
    this._state = 'ready'
    this._currentLap = 0
    this._previousLaps = []
    return undefined
  }

  public advanceTime(duration: unknown): unknown {
    if (this._state === 'running') {
      this._currentLap += duration as number
    }
    return undefined
  }
}
