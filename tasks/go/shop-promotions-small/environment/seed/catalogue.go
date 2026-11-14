// The catalogue: the products that the shop sells, by SKU, and their prices.
// All amounts are whole cents.

package shop

import (
	"errors"
	"fmt"
	"sort"
	"strings"
)

type Product struct {
	SKU          string
	Name         string
	UnitPrice    int
	Discontinued bool
}

type ProductRepository interface {
	Get(sku string) (Product, bool)
	Save(product Product)
	List() []Product
}

type InMemoryProductRepository struct {
	products map[string]Product
	order    []string
}

func NewInMemoryProductRepository() *InMemoryProductRepository {
	return &InMemoryProductRepository{products: map[string]Product{}}
}

func (r *InMemoryProductRepository) Get(sku string) (Product, bool) {
	product, ok := r.products[sku]
	return product, ok
}

func (r *InMemoryProductRepository) Save(product Product) {
	if _, ok := r.products[product.SKU]; !ok {
		r.order = append(r.order, product.SKU)
	}
	r.products[product.SKU] = product
}

func (r *InMemoryProductRepository) List() []Product {
	list := make([]Product, 0, len(r.order))
	for _, sku := range r.order {
		list = append(list, r.products[sku])
	}
	return list
}

type Catalogue struct {
	repository ProductRepository
}

func NewCatalogue(repository ProductRepository) *Catalogue {
	return &Catalogue{repository: repository}
}

func (c *Catalogue) AddProduct(sku, name string, unitPrice int) (Product, error) {
	if strings.TrimSpace(sku) == "" {
		return Product{}, errors.New("SKU must not be empty")
	}
	if strings.TrimSpace(name) == "" {
		return Product{}, errors.New("name must not be empty")
	}
	if err := checkPrice(unitPrice); err != nil {
		return Product{}, err
	}
	if _, ok := c.repository.Get(sku); ok {
		return Product{}, fmt.Errorf("product %s already exists", sku)
	}
	product := Product{SKU: sku, Name: name, UnitPrice: unitPrice}
	c.repository.Save(product)
	return product, nil
}

func (c *Catalogue) Product(sku string) (Product, error) {
	product, ok := c.repository.Get(sku)
	if !ok {
		return Product{}, fmt.Errorf("unknown product %s", sku)
	}
	return product, nil
}

func (c *Catalogue) ChangePrice(sku string, unitPrice int) error {
	product, err := c.Product(sku)
	if err != nil {
		return err
	}
	if err := checkPrice(unitPrice); err != nil {
		return err
	}
	product.UnitPrice = unitPrice
	c.repository.Save(product)
	return nil
}

func (c *Catalogue) Rename(sku, name string) error {
	product, err := c.Product(sku)
	if err != nil {
		return err
	}
	if strings.TrimSpace(name) == "" {
		return errors.New("name must not be empty")
	}
	product.Name = name
	c.repository.Save(product)
	return nil
}

// Search gives the products on sale whose name holds the text, in any case,
// in SKU order.
func (c *Catalogue) Search(text string) []Product {
	wanted := strings.ToLower(text)
	var found []Product
	for _, product := range c.ActiveProducts() {
		if strings.Contains(strings.ToLower(product.Name), wanted) {
			found = append(found, product)
		}
	}
	return found
}

func (c *Catalogue) Discontinue(sku string) error {
	product, err := c.Product(sku)
	if err != nil {
		return err
	}
	product.Discontinued = true
	c.repository.Save(product)
	return nil
}

// ActiveProducts gives the products on sale, in SKU order.
func (c *Catalogue) ActiveProducts() []Product {
	var active []Product
	for _, product := range c.repository.List() {
		if !product.Discontinued {
			active = append(active, product)
		}
	}
	sort.Slice(active, func(i, j int) bool { return active[i].SKU < active[j].SKU })
	return active
}

func checkPrice(unitPrice int) error {
	if unitPrice < 1 {
		return errors.New("unit price must be at least 1")
	}
	return nil
}
