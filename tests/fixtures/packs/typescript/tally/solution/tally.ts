import { normalise } from './text/names.ts'

export class Tally {
  private readonly counts = new Map<string, number>()

  public add(name: string, n = 1): void {
    const key = normalise(name)
    this.counts.set(key, this.count(key) + n)
  }

  public count(name: string): number {
    return this.counts.get(normalise(name)) ?? 0
  }

  public names(): string[] {
    return [...this.counts.keys()].sort()
  }

  public top(k: number): string[] {
    return this.names()
      .sort((a, b) => this.count(b) - this.count(a))
      .slice(0, k)
  }
}
