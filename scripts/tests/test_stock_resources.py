"""Small, local-only regression check for the approved low-memory budget."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts'))
import stock_deploy


class ResourceBudgetTests(unittest.TestCase):
    def budget(self, memory, disk, restore=False):
        self.assertTrue(callable(getattr(stock_deploy, 'require_resource_budget', None)),
                        'Resource validation must support the approved small ECS')
        return stock_deploy.require_resource_budget(memory, disk, include_restore=restore)

    def test_reported_818_mib_host_passes_bounded_serial_restore(self):
        report = self.budget(818 * 1024**2, 28 * 1024**3, True)
        self.assertEqual(report['required_memory_mib'], 768)

    def test_single_command_needs_512_mib_not_two_gib(self):
        self.assertEqual(self.budget(512 * 1024**2, 6 * 1024**3)['required_memory_mib'], 512)

    def test_insufficient_memory_is_not_bypassed(self):
        with self.assertRaisesRegex(stock_deploy.DeploymentError, 'memory.*511.*512'):
            self.budget(511 * 1024**2, 28 * 1024**3)
        with self.assertRaisesRegex(stock_deploy.DeploymentError, 'memory.*767.*768'):
            self.budget(767 * 1024**2, 28 * 1024**3, True)

    def test_disk_shortage_has_a_separate_measured_error(self):
        with self.assertRaisesRegex(stock_deploy.DeploymentError, 'disk.*1024.*6144'):
            self.budget(818 * 1024**2, 1024 * 1024**2, True)


if __name__ == '__main__':
    unittest.main()
