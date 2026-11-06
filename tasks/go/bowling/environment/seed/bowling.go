package bowling

type Game struct{}

func NewGame() *Game {
	panic("not implemented")
}

func (g *Game) Roll(pins int) error {
	panic("not implemented")
}

func (g *Game) Score() (int, error) {
	panic("not implemented")
}
