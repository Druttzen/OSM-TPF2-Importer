import unittest

from lua_remove_nil import drop_removed_nodes


class DropRemovedNodesTests(unittest.TestCase):
    def test_preserves_removed_nodes_referenced_by_area_rings(self):
        data = {
            "nodes": {
                1: {"pos": [0, 0]},
                2: {"pos": [1, 1], "removed": True},
                3: {"pos": [2, 2], "removed": True},
                4: {"pos": [3, 3], "removed": True},
                5: {"pos": [4, 4]},
            },
            "areas": {
                "grounds": [{"polygon": [1, 2, 5, 1]}],
                "forests": [{
                    "multipolygon": {
                        "outer": [[1, 3, 5, 1]],
                        "inner": [[1, 4, 5, 1]],
                    }
                }],
            },
            "paths": {"ground": [[1, 2, 3, 4, 5]]},
        }

        result = drop_removed_nodes(data)

        self.assertEqual(set(result["nodes"]), {1, 2, 3, 4, 5})
        self.assertEqual(result["paths"]["ground"], [[1, 5]])
        self.assertEqual(result["areas"]["grounds"][0]["polygon"], [1, 2, 5, 1])
        self.assertEqual(
            result["areas"]["forests"][0]["multipolygon"],
            {"outer": [[1, 3, 5, 1]], "inner": [[1, 4, 5, 1]]},
        )

        data["areas"] = {}
        result = drop_removed_nodes(data)
        self.assertEqual(set(result["nodes"]), {1, 5})


if __name__ == "__main__":
    unittest.main()
