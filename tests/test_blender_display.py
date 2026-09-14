"""Numerical guarantees for the Blender log-plus-power presentation."""
import unittest

import numpy as np

from src.blender_display import (LUMINANCE_WEIGHTS, brightness_comparison,
                                 display_luminance, display_rgb)


class BlenderDisplayTests(unittest.TestCase):
    def test_extra_compression_is_monotonic_and_preserves_black(self):
        values = np.r_[0., np.geomspace(1e-12, 60000., 1601)]
        for power in (.25, .6, 1., 2.):
            with self.subTest(power=power):
                mapped = display_luminance(values, display_power=power)
                self.assertEqual(mapped[0], 0.)
                self.assertAlmostEqual(mapped[-1], .4)
                self.assertTrue(np.all(np.diff(mapped) > 0))
        np.testing.assert_array_equal(display_rgb(np.zeros((2, 3))), np.zeros((2, 3)))
        np.testing.assert_array_equal(display_luminance([60000., 1e300]), [.4, .4])

    def test_power_one_has_known_logarithmic_landmarks(self):
        # Construct inputs whose normalized log is exactly 0, 1/4, 1/2, 1.
        # This checks the curve independently of any sibling project module.
        fraction = np.array([0., .25, .5, 1.])
        values = np.expm1(fraction*np.log1p(1e7))*60000./1e7
        expected = .4*fraction
        np.testing.assert_allclose(display_luminance(values, display_power=1.),
                                   expected, rtol=1e-14, atol=0.)

    def test_extra_power_reduces_contrast_without_reversing_brightness(self):
        # Model S / CIE data at the center and at one solar radius.
        center = [36619.5606, 53856.9276, 123003.430]
        surface = [1.11681031, .979615303, .917861236]
        comparison = brightness_comparison(center, surface)
        self.assertAlmostEqual(comparison['source_ratio'], 54947.0324, delta=.001)
        self.assertAlmostEqual(comparison['displayed_ratio'], 1.98221824, places=7)
        log_only = brightness_comparison(center, surface, display_power=1.)
        self.assertGreater(log_only['displayed_ratio'], comparison['displayed_ratio'])
        self.assertGreater(comparison['displayed_ratio'], 1.)
        # At the intended peak, bounded core texture still leaves glare room.
        self.assertLess(np.max(comparison['center_display_rgb'])*1.04 + .02, .95)

    def test_linear_chromaticity_and_gamut_are_preserved(self):
        colors = np.array([[.1, .6, 1.], [1., .05, .2], [.05, .05, 1.]])
        rgb = np.geomspace(1e-12, 1e8, 65)[:, None, None]*colors
        for peak in (.4, 1.):
            with self.subTest(peak=peak):
                result = display_rgb(rgb, display_peak=peak)
                self.assertTrue(np.all((result >= 0) & (result <= 1)))
                np.testing.assert_allclose(result/result[..., 2, None],
                                           rgb/rgb[..., 2, None], rtol=3e-14)
        hot = np.array([36619.5606, 53856.9276, 123003.430])
        np.testing.assert_allclose(display_rgb(hot)@LUMINANCE_WEIGHTS,
                                   display_luminance(hot@LUMINANCE_WEIGHTS), rtol=2e-14)

    def test_fixed_scale_and_exposure_are_frame_independent(self):
        signal = np.array([.001, .003, .004])
        np.testing.assert_array_equal(display_rgb([signal, [1e-20]*3])[0],
                                       display_rgb([signal, [1e12]*3])[0])
        np.testing.assert_allclose(display_rgb(signal, exposure_ev=3.),
                                   display_rgb(signal*8.), rtol=2e-14)
        np.testing.assert_allclose(display_rgb(signal, reference_luminance=6e4),
                                   display_rgb(signal*1e9, reference_luminance=6e13), rtol=2e-14)

    def test_invalid_parameters_and_signals_are_rejected(self):
        for key in ('compression', 'reference_luminance', 'display_peak', 'display_power'):
            for value in (0., -1., np.nan, np.inf):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    display_rgb([1., 1., 1.], **{key: value})
        for bad in ([1., -1., 1.], [np.nan, 1., 1.], [np.inf, 1., 1.], [1., 2.], 1.):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                display_rgb(bad)
        for settings in ({'display_peak': 1.1}, {'exposure_ev': np.inf}, {'exposure_ev': np.nan}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                display_rgb([1., 1., 1.], **settings)
        with self.assertRaises(ValueError):
            brightness_comparison([1., 1., 1.], [0., 0., 0.])


if __name__ == '__main__':
    unittest.main()
