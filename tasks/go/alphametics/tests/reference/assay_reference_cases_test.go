package alphametics

// This is an auto-generated file. Do not change it manually. Run the generator to update the file.
// See https://github.com/exercism/go#synchronizing-tests-and-instructions
// Source: exercism/problem-specifications
// Commit: 25c2ae5 build(deps): bump fast-uri from 3.1.0 to 3.1.2 (#2653)

type testCase struct {
	description   string
	input         string
	expected      map[string]int
	errorExpected bool
}

var testCases = []testCase{
	{
		description: "puzzle with three letters",
		input:       "I + BB == ILL",
		expected:    map[string]int{"B": 9, "I": 1, "L": 0},
	},
	{
		description:   "solution must have unique value for each letter",
		input:         "A == B",
		errorExpected: true,
	},
	{
		description:   "leading zero solution is invalid",
		input:         "ACA + DD == BD",
		errorExpected: true,
	},
	{
		description: "puzzle with four letters",
		input:       "AS + A == MOM",
		expected:    map[string]int{"A": 9, "M": 1, "O": 0, "S": 2},
	},
	{
		description: "puzzle with six letters",
		input:       "NO + NO + TOO == LATE",
		expected:    map[string]int{"A": 0, "E": 2, "L": 1, "N": 7, "O": 4, "T": 9},
	},
	{
		description: "puzzle with seven letters",
		input:       "HE + SEES + THE == LIGHT",
		expected:    map[string]int{"E": 4, "G": 2, "H": 5, "I": 0, "L": 1, "S": 9, "T": 7},
	},
	{
		description: "puzzle with eight letters",
		input:       "SEND + MORE == MONEY",
		expected:    map[string]int{"D": 7, "E": 5, "M": 1, "N": 6, "O": 0, "R": 8, "S": 9, "Y": 2},
	},
	{
		description: "puzzle with ten letters",
		input:       "AND + A + STRONG + OFFENSE + AS + A + GOOD == DEFENSE",
		expected:    map[string]int{"A": 5, "D": 3, "E": 4, "F": 7, "G": 8, "N": 0, "O": 2, "R": 1, "S": 6, "T": 9},
	},
}
