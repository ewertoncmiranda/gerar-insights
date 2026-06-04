"""
Configuração pytest compartilhada.
Define fixtures globais e configurações para os testes.
"""

import pytest
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path para imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def test_db_url():
    """URL de banco de dados para testes"""
    return "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def reset_modules():
    """Reset de módulos entre testes para evitar side effects"""
    yield
    # Cleanup aqui se necessário

