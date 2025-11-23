
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import shutil
import os

# Aggiungi la directory principale al percorso per trovare i moduli del progetto
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from benchmark_config import BenchmarkConfig, MetricCollectorConfig, PerfConfig
from local_runner import LocalRunner

class TestLocalRunnerIntegration(unittest.TestCase):

    def setUp(self):
        """Imposta una directory temporanea per gli output dei test."""
        self.test_output_dir = Path("test_benchmark_outputs")
        if self.test_output_dir.exists():
            shutil.rmtree(self.test_output_dir)
        self.test_output_dir.mkdir(exist_ok=True)

    def tearDown(self):
        """Pulisce la directory temporanea."""
        shutil.rmtree(self.test_output_dir)

    @patch('local_runner.DataHandler')
    @patch('local_runner.PSUtilCollector')
    @patch('local_runner.LocalRunner._pre_test_cleanup')
    def test_run_stress_ng_benchmark(self, mock_cleanup, mock_psutil_collector, mock_data_handler):
        """
        Testa un'esecuzione completa del benchmark stress-ng.
        Simula il generatore di carico e i collettori effettivi per evitare di eseguire comandi di sistema.
        """
        # --- Impostazione dei Mock ---
        # Mock dell'istanza del generatore
        mock_gen_instance = MagicMock()
        mock_gen_instance.get_result.return_value = {"status": "success"}

        # Mock dell'istanza del collettore
        mock_col_instance = MagicMock()
        mock_col_instance.name = "PSUtilCollector"
        mock_col_instance.get_data.return_value = [
            {'timestamp': '2025-01-01T12:00:00', 'cpu_percent': 50.0},
            {'timestamp': '2025-01-01T12:00:01', 'cpu_percent': 55.0},
        ]
        mock_psutil_collector.return_value = mock_col_instance
        
        # Mock del DataHandler
        mock_data_handler_instance = MagicMock()
        mock_data_handler_instance.process_test_results.return_value = None
        mock_data_handler.return_value = mock_data_handler_instance

        # --- Configurazione ed Esecuzione ---
        # Crea una configurazione minima per un test rapido
        config = BenchmarkConfig(
            repetitions=1,
            test_duration_seconds=1,
            warmup_seconds=0,
            cooldown_seconds=0,
            output_dir=self.test_output_dir / "results",
            data_export_dir=self.test_output_dir / "exports",
            report_dir=self.test_output_dir / "reports",
            # Disabilita altri collettori per semplificare il test
            collectors=MetricCollectorConfig(cli_commands=None, perf_config=PerfConfig(events=None), enable_ebpf=False)
        )

        registry = MagicMock()
        registry.create_generator.return_value = mock_gen_instance

        # Crea ed esegue il controller locale
        runner = LocalRunner(config, registry=registry)
        runner.run_benchmark("stress_ng")

        # --- Asserzioni ---
        # Verifica che il metodo di pulizia sia stato chiamato
        mock_cleanup.assert_called_once()

        # Verifica che il generatore sia stato inizializzato e utilizzato
        registry.create_generator.assert_called()
        mock_gen_instance.start.assert_called_once()
        mock_gen_instance.stop.assert_called_once()

        # Verifica che il collettore sia stato inizializzato e utilizzato
        mock_psutil_collector.assert_called_once()
        mock_col_instance.start.assert_called_once()
        mock_col_instance.stop.assert_called_once()
        mock_col_instance.save_data.assert_called_once()

        # Verifica che il DataHandler sia stato chiamato per processare i risultati
        mock_data_handler_instance.process_test_results.assert_called_once()
        
        # Verifica che save_data sia stato chiamato con il percorso corretto
        save_data_calls = mock_col_instance.save_data.call_args_list
        self.assertEqual(len(save_data_calls), 1)
        called_path = save_data_calls[0][0][0]
        self.assertEqual(called_path.name, "stress_ng_rep1_PSUtilCollector.csv")

if __name__ == '__main__':
    unittest.main()
