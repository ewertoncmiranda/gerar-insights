"""Diario operacional simulado (OPR-INS-4, DEC-OPR-1). Paper trading: nada aqui e ordem real.

Etapa da rotina da manha (start unico, DEC-AGT-1): processa, em ordem, cada pregao do mercado
posterior ao ultimo diario gravado (na primeira vez, desde o primeiro pregao com liquidez e
opiniao). Um pregao = uma transacao = uma linha em `diario_operacional`: rodar de novo nao duplica.

Em cada pregao P (so dados com data <= P; execucao sempre na ABERTURA, nunca no fechamento):
1. caixa rende o CDI do dia;
2. saidas decididas em P-1 executam na abertura de P (`saida.py`, OPR-INS-3);
3. entradas PENDENTES decididas em P-1 executam na abertura de P (ou esperam ate 5 pregoes);
4. posicoes abertas sao avaliadas no fechamento de P (stop movel, motivo de saida para P+1);
5. novas entradas: ativo elegivel (OPR-INS-1) com opiniao SINAL_POSITIVO recente, ordenado por
   liquidez; tamanho pelo `risco.py` (OPR-INS-2); fica PENDENTE para a abertura de P+1;
6. patrimonio no fechamento, retorno bruto/liquido, CDI bruto e liquido de IR, excesso e drawdown.
Imposto estimado (OPR-INS-5) e status pela trava (OPR-INS-6) ainda nao entram: imposto NULL e
status EM_OBSERVACAO.
"""

from __future__ import annotations

import logging
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from app.operacional import risco, saida
from app.operacional.custos import custo_por_lado
from app.operacional.elegibilidade import ALTA, INSUFICIENTE, LimitesLiquidez, faixa_de_liquidez
from app.operacional.repositorio import RepositorioOperacional
from app.operacional.repositorio_diario import JANELA_OPINIAO, RepositorioDiario
from app.operacional.servico import avaliar_pregao, versao_regra

log = logging.getLogger("operacional")

POSITIVO = "SINAL_POSITIVO"
ESPERA_ENTRADA = 5  # pregoes que uma entrada PENDENTE espera o ativo negociar antes de ser cancelada
LOTE = 100
HORIZONTES = (21, 63, 126)
STATUS_COLETA = "EM_OBSERVACAO"  # OPR-INS-6 decide o status de verdade
D0 = Decimal(0)


def aliquota_ir_renda_fixa(dias_corridos: int) -> Decimal:
    """Tabela regressiva (benchmark justo: CDI liquido de IR, DEC-OPR-1)."""
    if dias_corridos <= 180:
        return Decimal("0.225")
    if dias_corridos <= 360:
        return Decimal("0.20")
    if dias_corridos <= 720:
        return Decimal("0.175")
    return Decimal("0.15")


def limites_de_sizing(parametros: dict) -> risco.LimitesSizing:
    """A V23 guarda o sizing em `tamanho` (e `max_participacao_adtv_21d`); o risco.py le `sizing`."""
    tamanho = dict(parametros.get("tamanho") or {})
    if "max_participacao_adtv_21d" in tamanho:
        tamanho.setdefault("max_participacao_adtv", tamanho["max_participacao_adtv_21d"])
    return risco.LimitesSizing.de_parametros({"sizing": {**tamanho, **(parametros.get("sizing") or {})}})


@dataclass
class ResumoDiario:
    pregoes: list[date] = field(default_factory=list)
    abertas: int = 0
    fechadas: int = 0
    pendentes: int = 0
    canceladas: int = 0


def _d(valor) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def _q(valor: Decimal, casas: str = "0.01") -> Decimal:
    return valor.quantize(Decimal(casas))


class DiarioOperacional:
    def __init__(self, repo: RepositorioDiario | None = None, repo_operacional: RepositorioOperacional | None = None,
                 versao: str | None = None):
        self.repo = repo or RepositorioDiario()
        self.repo_op = repo_operacional or RepositorioOperacional()
        self.versao = versao or versao_regra()

    # ---------------------------------------------------------------------------------------------
    def executar(self, sessao_factory) -> ResumoDiario:
        resumo = ResumoDiario()
        with sessao_factory() as db:
            mercado = self.repo.pregoes_mercado(db)
            ultimo = self.repo.ultimo_diario(db, self.versao)
            ate = self.repo.ultimo_pregao_com_liquidez(db)
            inicio = (ultimo["data_pregao"] if ultimo else None)
            primeiro = self.repo.primeiro_pregao_possivel(db) if ultimo is None else None
        if ate is None or (ultimo is None and primeiro is None):
            log.info("Diario operacional: sem liquidez/opiniao ainda; nada a fazer")
            return resumo
        alvo = mercado[bisect_right(mercado, inicio):bisect_right(mercado, ate)] if inicio else \
            mercado[bisect_left(mercado, primeiro):bisect_right(mercado, ate)]
        for p in alvo:
            with sessao_factory() as db:
                self._pregao(db, p, mercado, resumo)
                db.commit()
            resumo.pregoes.append(p)
        return resumo

    # ---------------------------------------------------------------------------------------------
    def _pregao(self, db, p: date, mercado: list[date], resumo: ResumoDiario) -> None:
        repo, versao = self.repo, self.versao
        parametros = self.repo_op.parametros_da_regra(db, versao)
        limites_liq = LimitesLiquidez.de_parametros(parametros)
        p_saida = saida.ParametrosSaida.de_parametros(parametros)
        p_sizing = limites_de_sizing(parametros)
        capital = Decimal(str(parametros.get("capital_teorico", 100000)))
        indice_p = bisect_left(mercado, p)
        anterior = repo.ultimo_diario(db, versao)
        inicio = anterior["inicio"] if anterior else p
        caixa = _d(anterior["caixa"]) if anterior else capital
        cdi_dia = repo.cdi_do_dia(db, p)
        if anterior:
            caixa = _q(caixa * (1 + cdi_dia))
        custos_dia = D0
        abertas_dia = fechadas_dia = 0

        ops = repo.operacoes_em_curso(db, versao)
        simbolos = {o["simbolo"] for o in ops}
        cot = repo.cotacoes(db, p, simbolos)
        _, elegibilidade = avaliar_pregao(db, p, versao=versao, repositorio=self.repo_op)
        por_simbolo = {e.simbolo: e for e in elegibilidade}
        espera = mercado[max(0, indice_p - JANELA_OPINIAO + 1)]
        opinioes = repo.opinioes(db, p, espera)

        # 2. saidas decididas no pregao anterior: abertura de P
        for op in [o for o in ops if o["status"] == "ABERTA" and o["data_decisao_saida"] is not None]:
            abertura = _d((cot.get(op["simbolo"]) or {}).get("abertura"))
            if abertura is None:
                continue  # ativo nao negociou: sai na primeira abertura disponivel
            bruto_saida = abertura * op["quantidade"]
            metr = por_simbolo[op["simbolo"]].metricas if op["simbolo"] in por_simbolo else {}
            spread, estimado = _d(metr.get("spread_mediano_63d")), _d(metr.get("spread_estimado_63d"))
            c_saida = custo_por_lado(bruto_saida, spread, parametros, estimado)
            caixa += bruto_saida - c_saida
            custos_dia += c_saida
            bruto = (abertura - op["preco_entrada"]) * op["quantidade"]
            pos_custos = bruto - (op["custos_entrada"] or D0) - c_saida
            repo.atualizar(db, op["id"], {"status": "FECHADA", "data_saida": p, "preco_saida": abertura,
                                          "custos_saida": c_saida, "resultado_bruto": _q(bruto),
                                          "resultado_pos_custos": _q(pos_custos)})
            op["status"] = "FECHADA"
            resumo.fechadas += 1
            fechadas_dia += 1
            repo.evento(db, versao, "POSICAO_FECHADA", p, {
                "simbolo": op["simbolo"], "motivo_saida": op["motivo_saida"], "preco_saida": str(abertura),
                "resultado_pos_custos": str(_q(pos_custos))}, op["simbolo"], op["id"])

        # 3. entradas pendentes: abertura de P
        for op in [o for o in ops if o["status"] == "PENDENTE"]:
            abertura = _d((cot.get(op["simbolo"]) or {}).get("abertura"))
            decidida = bisect_left(mercado, op["data_decisao_entrada"])
            if abertura is None:
                if indice_p - decidida > ESPERA_ENTRADA:
                    repo.atualizar(db, op["id"], {"status": "CANCELADA"})
                    op["status"] = "CANCELADA"
                    resumo.canceladas += 1
                continue
            metr = por_simbolo[op["simbolo"]].metricas if op["simbolo"] in por_simbolo else {}
            spread, estimado = _d(metr.get("spread_mediano_63d")), _d(metr.get("spread_estimado_63d"))
            quantidade = int(op["quantidade"])
            while quantidade > 0 and abertura * quantidade + custo_por_lado(abertura * quantidade, spread, parametros, estimado) > caixa:
                quantidade = quantidade - LOTE if quantidade > LOTE else int((caixa / abertura * Decimal("0.99")).to_integral_value(ROUND_FLOOR))
                if quantidade * abertura < p_sizing.posicao_minima:
                    quantidade = 0
            if quantidade <= 0:
                repo.atualizar(db, op["id"], {"status": "CANCELADA"})
                op["status"] = "CANCELADA"
                resumo.canceladas += 1
                continue
            valor = abertura * quantidade
            c_entrada = custo_por_lado(valor, spread, parametros, estimado)
            caixa -= valor + c_entrada
            custos_dia += c_entrada
            stop = saida.stop_inicial(abertura, op["atr_entrada"], p_saida)
            campos = {"status": "ABERTA", "data_entrada": p, "preco_entrada": abertura, "quantidade": quantidade,
                      "valor_entrada": _q(valor), "stop_inicial": stop, "stop_atual": stop,
                      "maxima_desde_entrada": abertura, "custos_entrada": c_entrada}
            repo.atualizar(db, op["id"], campos)
            op.update(campos)
            resumo.abertas += 1
            abertas_dia += 1
            repo.evento(db, versao, "POSICAO_ABERTA", p, {
                "simbolo": op["simbolo"], "horizonte_pregoes": op["horizonte_pregoes"], "quantidade": quantidade,
                "preco_entrada": str(abertura), "stop_inicial": str(stop)}, op["simbolo"], op["id"])

        # 4. avaliacao das abertas no fechamento de P
        abertas = [o for o in ops if o["status"] == "ABERTA" and o["data_decisao_saida"] is None]
        fatos = repo.fatos_relevantes(db, p, {o["simbolo"] for o in abertas})
        recentes = repo.liquidez_recente(db, p, {o["simbolo"] for o in abertas}, p_saida.dias_iliquido_saida)
        for op in abertas:
            c = cot.get(op["simbolo"])
            if not c or c["fechamento"] is None:
                continue  # sem pregao do ativo hoje: nada muda
            seguidos = 0
            for linha in recentes.get(op["simbolo"], []):
                if faixa_de_liquidez(linha, limites_liq)[0] != INSUFICIENTE:
                    break
                seguidos += 1
            posicao = saida.Posicao(op["simbolo"], op["horizonte_pregoes"], op["data_entrada"], op["preco_entrada"],
                                    op["atr_entrada"], op["stop_atual"], op["maxima_desde_entrada"])
            dia = saida.PregaoDaPosicao(
                data_pregao=p, fechamento=_d(c["fechamento"]), maxima=_d(c["maxima"] or c["fechamento"]),
                pregoes_em_posicao=indice_p - bisect_left(mercado, op["data_entrada"]) + 1,
                fatos_relevantes=tuple(fatos.get(op["simbolo"], [])),
                ajuste_serie=(por_simbolo.get(op["simbolo"]).metricas.get("ajuste_serie", "BRUTA")
                              if op["simbolo"] in por_simbolo else "BRUTA"),
                dias_insuficiente_seguidos=seguidos if recentes.get(op["simbolo"]) else None,
                opiniao=opinioes.get((op["simbolo"], op["horizonte_pregoes"])))
            av = saida.avaliar(posicao, dia, p_saida)
            campos = {"stop_atual": av.posicao.stop_atual, "maxima_desde_entrada": av.posicao.maxima_desde_entrada}
            if av.sai:
                campos.update({"data_decisao_saida": p, "motivo_saida": av.motivo_saida,
                               "motivo_saida_json": av.motivo_saida_json()})
            repo.atualizar(db, op["id"], campos)
            op.update(campos)

        # 6a. marcacao a mercado (antes das novas entradas, que so executam em P+1)
        em_carteira = [o for o in ops if o["status"] == "ABERTA"]
        fechamentos = repo.ultimo_fechamento(db, p, {o["simbolo"] for o in em_carteira})
        posicoes_valor = sum((_d(fechamentos.get(o["simbolo"]) or o["preco_entrada"]) * o["quantidade"]
                              for o in em_carteira), D0)
        patrimonio = _q(caixa + posicoes_valor)

        # 5. novas entradas (PENDENTE para a abertura de P+1)
        pendentes = [o for o in ops if o["status"] == "PENDENTE"]
        ocupados = {o["simbolo"] for o in em_carteira + pendentes}
        setores = repo.setores(db)
        exposicao_setor: dict[str, Decimal] = {}
        for o in em_carteira:
            setor = setores.get(o["simbolo"], "SEM_SETOR")
            exposicao_setor[setor] = exposicao_setor.get(setor, D0) + _d(fechamentos.get(o["simbolo"]) or o["preco_entrada"]) * o["quantidade"]
        reservado = D0
        for o in pendentes:
            setor = setores.get(o["simbolo"], "SEM_SETOR")
            valor_previsto = _d((o["motivo_entrada_json"] or {}).get("valor_previsto")) or D0
            exposicao_setor[setor] = exposicao_setor.get(setor, D0) + valor_previsto
            reservado += valor_previsto
        candidatos = []
        for e in elegibilidade:
            if not e.elegivel or e.simbolo in ocupados:
                continue
            horizonte = next((h for h in HORIZONTES if opinioes.get((e.simbolo, h)) == POSITIVO), None)
            if horizonte:
                candidatos.append((e, horizonte))
        candidatos.sort(key=lambda par: (par[0].faixa != ALTA, -float(par[0].metricas.get("volume_financeiro_medio_63d") or 0)))
        precos = repo.cotacoes(db, p, {e.simbolo for e, _ in candidatos})
        posicoes_abertas = len(em_carteira) + len(pendentes)
        for e, horizonte in candidatos:
            fechamento = _d((precos.get(e.simbolo) or {}).get("fechamento"))
            if fechamento is None:
                continue
            setor = setores.get(e.simbolo, "SEM_SETOR")
            r = risco.calcular(capital=patrimonio, caixa=caixa - reservado, preco=fechamento,
                               atr14=_d(e.metricas.get("atr14")), faixa=e.faixa,
                               percentil_volatilidade=_d(e.metricas.get("percentil_volatilidade")),
                               vol21d=_d(e.metricas.get("volume_financeiro_medio_21d")),
                               exposicao_atual_ativo=D0, exposicao_atual_setor=exposicao_setor.get(setor, D0),
                               posicoes_abertas=posicoes_abertas, limites=p_sizing)
            if not r.elegivel:
                continue
            quantidade = r.quantidade_inteira + r.quantidade_fracionaria
            motivo = {"sinal": {"opiniao": POSITIVO, "horizonte_pregoes": horizonte},
                      "elegibilidade": e.como_json(), "valor_previsto": str(r.valor_financeiro),
                      "sizing": {"quantidade_inteira": r.quantidade_inteira,
                                 "quantidade_fracionaria": r.quantidade_fracionaria,
                                 "valor_financeiro": str(r.valor_financeiro), "redutores": r.redutores_aplicados,
                                 "detalhe": r.detalhe}, "execucao": saida.EXECUCAO}
            if repo.inserir_pendente(db, versao, {"simbolo": e.simbolo, "setor": setor, "horizonte": horizonte,
                                                  "data": p, "quantidade": quantidade,
                                                  "atr": _d(e.metricas.get("atr14")), "faixa": e.faixa,
                                                  "motivo": motivo}):
                resumo.pendentes += 1
                posicoes_abertas += 1
                reservado += r.valor_financeiro
                exposicao_setor[setor] = exposicao_setor.get(setor, D0) + r.valor_financeiro

        # 6b. diario do pregao
        anterior_patrimonio = _d(anterior["patrimonio"]) if anterior else capital
        cdi_acum = ((1 + _d(anterior["cdi_acumulado"] or 0)) * (1 + cdi_dia) - 1) if anterior else cdi_dia
        dias = (p - inicio).days
        cdi_liq = cdi_acum * (1 - aliquota_ir_renda_fixa(dias))
        ret_liq_dia = patrimonio / anterior_patrimonio - 1
        ret_bruto_dia = (patrimonio + custos_dia) / anterior_patrimonio - 1
        ret_acum = patrimonio / capital - 1
        pico = max(_d(anterior["pico"]) if anterior else capital, patrimonio)
        drawdown = patrimonio / pico - 1
        dd_max = min(_d(anterior["drawdown_maximo"]) if anterior and anterior["drawdown_maximo"] is not None else D0, drawdown)
        q8 = "0.00000001"
        linha = {
            "data_pregao": p, "capital_inicial": capital, "patrimonio": patrimonio, "caixa": _q(caixa),
            "exposicao": _q(posicoes_valor / patrimonio if patrimonio else D0, q8),
            "posicoes_abertas": len(em_carteira), "operacoes_abertas_dia": abertas_dia,
            "operacoes_fechadas_dia": fechadas_dia,
            "retorno_bruto_dia": _q(ret_bruto_dia, q8), "retorno_liquido_dia": _q(ret_liq_dia, q8),
            "retorno_liquido_acumulado": _q(ret_acum, q8), "cdi_dia": _q(cdi_dia, q8),
            "cdi_acumulado": _q(cdi_acum, q8), "cdi_liquido_ir_acumulado": _q(cdi_liq, q8),
            "excesso_sobre_cdi_liquido": _q(ret_acum - cdi_liq, q8),
            "drawdown": _q(drawdown, q8), "drawdown_maximo": _q(dd_max, q8),
            "imposto_estimado_mes": None, "violacoes_liquidez": 0,
            "status_sistema": STATUS_COLETA,
            "motivos_status_json": {"motivo": "coleta em andamento; trava de operabilidade na OPR-INS-6",
                                    "pregoes_no_diario": bisect_right(mercado, p) - bisect_left(mercado, inicio)},
        }
        repo.gravar_diario(db, versao, linha)
        repo.evento(db, versao, "DIARIO_AVALIADO", p, {k: str(v) for k, v in linha.items() if k != "motivos_status_json"})
        log.info("Diario %s | patrimonio=%s | caixa=%s | abertas=%d | novas pendentes=%d", p, patrimonio, _q(caixa),
                 len(em_carteira), resumo.pendentes)


def main() -> int:
    """Etapa da rotina da manha (`cargas-etl.ps1`): sem argumentos, processa os pregoes novos."""
    from app.config.config_logger import setup_logger  # noqa: PLC0415
    from app.config.database_config import ConfigDatabase  # noqa: PLC0415

    logger = setup_logger()
    resumo = DiarioOperacional().executar(ConfigDatabase().session)
    logger.info("Diario operacional | pregoes=%d | abertas=%d | fechadas=%d | pendentes=%d | canceladas=%d",
                len(resumo.pregoes), resumo.abertas, resumo.fechadas, resumo.pendentes, resumo.canceladas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
