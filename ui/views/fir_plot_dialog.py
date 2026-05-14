import json
import numpy as np
from scipy import signal
import logging

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QMessageBox, QComboBox, QLabel
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)

class FirPlotDialog(QDialog):
    def __init__(self, datalogger_name: str, filters: list, parent=None):
        super().__init__(parent)
        self.filters = sorted(filters, key=lambda x: x.stage_number)
        self.setWindowTitle(f"Filter Chain Analysis - Datalogger: {datalogger_name}")
        self.resize(900, 700)
        
        layout = QVBoxLayout(self)
        
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("<b>Select Chain Stage:</b>"))
        
        self.stage_selector = QComboBox()
        for f in self.filters:
            label = f"Stage {f.stage_number} ({f.filter_type}) - Decimation: {f.decimation_factor}"
            self.stage_selector.addItem(label, f)
        
        self.stage_selector.currentIndexChanged.connect(self._on_stage_changed)
        top_bar.addWidget(self.stage_selector)
        top_bar.addStretch()
        layout.addLayout(top_bar)
        
        self.fig = Figure(figsize=(8, 8))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        
        if self.filters:
            self._plot_filter(self.filters[0])

    def _on_stage_changed(self, index):
        """Updates the plot when another stage is selected."""
        selected_filter = self.stage_selector.itemData(index)
        if selected_filter:
            self._plot_filter(selected_filter)

    def _plot_filter(self, filter_obj):
        """Performs DSP calculation and updates the plot canvas with delay management."""
        try:
            raw_data = json.loads(filter_obj.coefficients)
            if not raw_data:
                raise ValueError("Empty or missing JSON data.")
            
            # --- FIX: Safe extraction of numeric array from JSON Dictionary ---
            if isinstance(raw_data, dict):
                if 'numerators' in raw_data:
                    coefficients = raw_data['numerators']
                elif 'Numerator' in raw_data:
                    coefficients = raw_data['Numerator']
                elif 'coefficients' in raw_data:
                    coefficients = raw_data['coefficients']
                elif 'b' in raw_data: # In case of IIR filters
                    coefficients = raw_data['b']
                else:
                    for key, val in raw_data.items():
                        if isinstance(val, list):
                            coefficients = val
                            break
            else:
                coefficients = raw_data
                
            if not isinstance(coefficients, list):
                raise ValueError(f"Unable to extract numeric array from format: {type(coefficients)}")
                
            if len(coefficients) == 0:
                raise ValueError("The coefficients list is empty (zero elements).")
                
            coefficients = [float(c) for c in coefficients]

        except Exception as e:
            logger.error(f"Error parsing coefficients for stage {filter_obj.stage_number}: {e}")
            self.fig.clear()
            ax = self.fig.add_subplot(111)
            ax.text(0.5, 0.5, f"Error loading data:\n{e}",
                    ha='center', va='center', color='red', fontsize=12)
            ax.set_axis_off()
            self.canvas.draw()
            return
            
        self.fig.clear()
        
        info_text = (f"Stage {filter_obj.stage_number} | Estimated delay: {filter_obj.estimated_delay} s | "
                     f"Applied correction: {filter_obj.correction_applied} s")
        self.fig.suptitle(info_text, fontsize=10, color='gray')

        # --- PLOT 1: Impulse Response (Time) ---
        ax1 = self.fig.add_subplot(211)
        ax1.set_title("Impulse Response (Coefficients)")
        
        if len(coefficients) < 100:
            ax1.stem(range(len(coefficients)), coefficients, basefmt="black")
        else:
            ax1.plot(range(len(coefficients)), coefficients, color='blue', alpha=0.7)
            
        ax1.set_xlabel("n (Samples)")
        ax1.set_ylabel("Amplitude")
        ax1.grid(True, linestyle=':', alpha=0.6)
        
        # --- PLOT 2: Frequency Response (Magnitude) ---
        ax2 = self.fig.add_subplot(212)
        
        w, h = signal.freqz(coefficients, worN=8000)
        
        if filter_obj.input_sample_rate > 0:
            frequenze = (w * filter_obj.input_sample_rate) / (2 * np.pi)
            ax2.set_xlabel("Frequency (Hz)")
            
            dec_factor = filter_obj.decimation_factor
            if not dec_factor or dec_factor == 0:
                dec_factor = 1 
                
            real_output_sample_rate = filter_obj.input_sample_rate / dec_factor
            
            nyquist_out = real_output_sample_rate / 2
            ax2.axvline(nyquist_out, color='green', linestyle='--', label=f'Nyquist Out ({nyquist_out:.2f} Hz)')
            ax2.legend()
        else:
            frequenze = w / np.pi
            ax2.set_xlabel("Normalized Frequency (×π rad/sample)")

        modulo_db = 20 * np.log10(np.maximum(np.abs(h), 1e-12))
        
        ax2.set_title("Frequency Response (Magnitude)")
        ax2.plot(frequenze, modulo_db, color='red', linewidth=1.2)
        ax2.set_ylabel("Amplitude (dB)")
        ax2.set_ylim([-130, 5])
        ax2.grid(True, which='both', linestyle=':', alpha=0.6)
        
        self.fig.tight_layout(rect=[0, 0.03, 1, 0.95])
        self.canvas.draw()