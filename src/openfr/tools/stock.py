"""
Stock data tools based on AKShare.

本模块对外暴露 A 股行情、搜索、板块、概念等 @tool，具体实现与数据拉取逻辑在 stock_core 中。
"""

from typing import Callable
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import akshare as ak
import pandas as pd
import re
from langchain_core.tools import tool

from openfr.tools.base import format_dataframe, validate_stock_code, validate_date, retry_on_network_error
from openfr.tools.cache import persistent_cached
from openfr.tools.stock_hk import search_stock_hk
from openfr.tools.constants import CONCEPT_STOCKS_TOTAL_TIMEOUT
from openfr.tools.stock_core import (
    _fetch_stock_spot,
    _fetch_stock_spot_sina,
    _fetch_stock_info,
    _fetch_stock_history,
    _get_stock_list_code_name_cached,
    _fetch_stock_news,
    _fetch_hot_stocks,
    _fetch_industry_boards,
    _fetch_industry_cons_em,
    _fetch_concept_boards,
    _realtime_from_spot_row,
    _norm_code,
    _get_pe_pb_from_spot,
    _fmt_finance_val,
    _fetch_stock_financial_analysis_indicator,
    _parse_em_finance_row,
    _extract_growth_from_abstract,
    _fetch_roe_revg_profg_fallback,
    _invoke_sub_tool,
    _get_concept_stocks_impl,
    _to_em_symbol,
    _to_em_symbol_dot,
    _call_ak_with_symbol_or_stock,
)


@persistent_cached(ttl=6 * 60 * 60)
def _fetch_valuation_comparison(symbol: str) -> pd.DataFrame:
    """获取东财估值比较数据，财务估值类接口使用本地缓存。"""
    return ak.stock_zh_valuation_comparison_em(symbol=symbol)


@tool
def get_stock_realtime(symbol: str) -> str:
    """
    获取A股实时行情数据。

    Args:
        symbol: 股票代码，如 "000001" (平安银行) 或 "600519" (贵州茅台)

    Returns:
        股票的实时行情信息，包括最新价、涨跌幅、成交量等
    """
    try:
        symbol = validate_stock_code(symbol)

        # 优先个股信息接口；失败时降级为全市场行情列表按代码筛选
        try:
            df = _fetch_stock_info(symbol)
            if not df.empty:
                info_dict = {}
                for _, row in df.iterrows():
                    info_dict[row['item']] = row['value']
                output = f"股票 {symbol} 实时行情:\n"
                output += f"  股票代码: {info_dict.get('股票代码', symbol)}\n"
                output += f"  股票简称: {info_dict.get('股票简称', 'N/A')}\n"
                output += f"  最新价: {info_dict.get('最新', 'N/A')}\n"
                output += f"  涨跌幅: {info_dict.get('涨跌幅', 'N/A')}\n"
                output += f"  今开: {info_dict.get('今开', 'N/A')}\n"
                output += f"  昨收: {info_dict.get('昨收', 'N/A')}\n"
                output += f"  最高: {info_dict.get('最高', 'N/A')}\n"
                output += f"  最低: {info_dict.get('最低', 'N/A')}\n"
                output += f"  成交量: {info_dict.get('成交量', 'N/A')}\n"
                output += f"  成交额: {info_dict.get('成交额', 'N/A')}\n"
                output += f"  总市值: {info_dict.get('总市值', 'N/A')}\n"
                output += f"  流通市值: {info_dict.get('流通市值', 'N/A')}\n"
                return output
        except Exception:
            pass

        # 降级：全市场行情列表（东财→新浪）按代码查，统一用 _norm_code 匹配
        def _find_in_spot(df: pd.DataFrame) -> pd.Series | None:
            if df is None or df.empty:
                return None
            code_col = next((c for c in ("代码", "code", "symbol") if c in df.columns), df.columns[0] if len(df.columns) else None)
            if code_col is None:
                return None
            target = _norm_code(symbol)
            code_ser = df[code_col].astype(str).apply(lambda x: _norm_code(x))
            mask = code_ser == target
            if not mask.any():
                return None
            return df.loc[mask].iloc[0]

        spot_df = _fetch_stock_spot()
        row = _find_in_spot(spot_df)
        if row is not None:
            return _realtime_from_spot_row(symbol, row)
        # 东财常断连时单独试新浪行情
        try:
            sina_df = _fetch_stock_spot_sina()
            row = _find_in_spot(sina_df)
            if row is not None:
                return _realtime_from_spot_row(symbol, row)
        except Exception:
            pass
        # 兜底：用最近交易日日线当「最新行情」（东财/新浪 spot 均不可用时）
        try:
            end_d = datetime.now().strftime("%Y%m%d")
            start_d = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            hist = _fetch_stock_history(symbol=symbol, period="daily", start_date=start_d, end_date=end_d)
            if hist is not None and not hist.empty:
                last = hist.iloc[-1]
                out = f"股票 {symbol} 实时行情（来自最近交易日）:\n"
                out += f"  股票代码: {symbol}\n"
                out += f"  股票简称: （见 get_stock_info）\n"
                out += f"  日期: {last.get('日期', 'N/A')}\n"
                out += f"  最新价(收盘): {last.get('收盘', 'N/A')}\n"
                out += f"  涨跌幅: {last.get('涨跌幅', 'N/A')}\n"
                out += f"  今开: {last.get('开盘', 'N/A')}\n"
                out += f"  昨收: {last.get('昨收', hist.iloc[-2].get('收盘', 'N/A') if len(hist) >= 2 else 'N/A')}\n"
                out += f"  最高/最低: {last.get('最高', 'N/A')} / {last.get('最低', 'N/A')}\n"
                out += f"  成交量: {last.get('成交量', 'N/A')}\n"
                out += f"  成交额: {last.get('成交额', 'N/A')}\n"
                out += "  （数据来自日线，非实时；交易时间请以交易所为准）\n"
                return out
        except Exception:
            pass
        return f"未找到股票代码 {symbol} 的数据"
    except Exception as e:
        return f"获取实时行情失败: {str(e)[:200]}"


@tool
def get_stock_history(
    symbol: str,
    start_date: str = "",
    end_date: str = "",
    period: str = "daily",
    adjust: str = "qfq",
) -> str:
    """
    获取A股历史行情数据。

    Args:
        symbol: 股票代码，如 "000001"
        start_date: 开始日期，格式 YYYYMMDD，如 "20230101"
        end_date: 结束日期，格式 YYYYMMDD，如 "20231231"
        period: 周期，可选 "daily"(日), "weekly"(周), "monthly"(月)
        adjust: 复权类型，"qfq"(前复权), "hfq"(后复权), ""(不复权)

    Returns:
        历史K线数据
    """
    try:
        symbol = validate_stock_code(symbol)

        kwargs = {
            "symbol": symbol,
            "period": period,
            "adjust": adjust,
        }

        if start_date:
            kwargs["start_date"] = validate_date(start_date)
        if end_date:
            kwargs["end_date"] = validate_date(end_date)

        df = _fetch_stock_history(**kwargs)

        if df.empty:
            return (
                f"未找到股票 {symbol} 的历史数据。\n"
                "数据源可能临时不可用，请稍后重试或缩短查询区间。"
            )

        stale_note = ""
        if getattr(df, "attrs", {}).get("_openfr_stale"):
            stale_note = "（数据源实时请求失败，以下为最近缓存数据）"

        return f"股票 {symbol} 历史行情 ({period}){stale_note}:\n\n{format_dataframe(df)}"
    except Exception as e:
        return f"获取历史行情失败: {str(e)[:200]}"


@tool
def get_stock_info(symbol: str) -> str:
    """
    获取个股基本信息。

    Args:
        symbol: 股票代码，如 "000001"

    Returns:
        股票的基本信息，包括公司名称、行业、市值等
    """
    try:
        symbol = validate_stock_code(symbol)

        # 先试全市场行情（东财/新浪），按代码取一行，通常比个股详情接口更稳定
        spot_df = _fetch_stock_spot()
        fallback_row = None
        if not spot_df.empty and "代码" in spot_df.columns:
            code_str = spot_df["代码"].astype(str)
            mask = (
                (code_str == symbol)
                | code_str.str.endswith("." + symbol)
                | (code_str.str.replace(r"\D", "", regex=True) == symbol)
            )
            stock_data = spot_df.loc[mask]
            if not stock_data.empty:
                fallback_row = stock_data.iloc[0]

        # 再试东财个股详情（公司名、行业等更全）；失败则用上面行情行
        try:
            df = _fetch_stock_info(symbol)
            if not df.empty:
                output = f"股票 {symbol} 基本信息:\n"
                for _, row in df.iterrows():
                    output += f"  {row['item']}: {row['value']}\n"
                return output
        except Exception:
            pass

        if fallback_row is not None:
            row = fallback_row
            output = f"股票 {symbol} 基本信息（来自行情列表）:\n"
            for col in ["代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "总市值", "流通市值", "今开", "昨收", "最高", "最低"]:
                if col in row.index and pd.notna(row.get(col)) and str(row.get(col)).strip() != "":
                    output += f"  {col}: {row[col]}\n"
            return output

        return f"未找到股票 {symbol} 的基本信息"
    except Exception as e:
        return f"获取股票信息失败: {str(e)[:200]}"



@tool
def get_stock_financials(symbol: str) -> str:
    """
    获取 A股核心财务指标（PE、PB、ROE、营收/利润增速等）。

    主要包含：
    - 估值类：市盈率（PE）、市净率（PB）
    - 盈利能力：净资产收益率（ROE）
    - 成长性：营业收入同比增速、净利润同比增速
    数据来源：东方财富主要指标/新浪关键指标，与东财页面口径一致时优先取年报。
    """
    def _fmt(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "N/A"
        return str(val)

    try:
        symbol = validate_stock_code(symbol)
        df = _fetch_stock_financial_analysis_indicator(symbol)
        pe, pb, roe, rev_g, prof_g = None, None, None, None, None
        report_period = None

        if df is not None and not df.empty:
            # 长表格式：列含 指标名称、报告期、指标值（兼容 指标/名称/项目 + 值/数值/value）
            name_candidates = ["指标名称", "指标", "名称", "项目", "item", "name"]
            value_candidates = ["指标值", "数值", "值", "value", "数据"]
            name_col = next((c for c in name_candidates if c in df.columns), None)
            value_col = next((c for c in value_candidates if c in df.columns), None)
            if name_col and value_col:
                period_col = next((c for c in ["报告期", "日期", "date", "报告日期"] if c in df.columns), None)
                if period_col:
                    df = df.sort_values(period_col, ascending=False)
                    report_period = str(df[period_col].iloc[0])
                    first_period = df[period_col].iloc[0]
                    sub = df[df[period_col] == first_period]
                else:
                    sub = df
                for _, r in sub.iterrows():
                    name = str(r.get(name_col, ""))
                    val = r.get(value_col)
                    if val is None or (isinstance(val, float) and pd.isna(val)):
                        continue
                    if "净资产收益率" in name or "ROE" in name.upper():
                        roe = val
                    elif "市盈率" in name or ("PE" in name.upper() and "PEG" not in name.upper()):
                        pe = val
                    elif "市净率" in name or "PB" in name.upper():
                        pb = val
                    elif "主营业务收入增长率" in name or ("营业收入" in name and "增长" in name):
                        rev_g = val
                    elif "净利润增长率" in name or ("净利润" in name and "增长" in name):
                        prof_g = val
            if (name_col is None or value_col is None) or (pe is None and pb is None and roe is None):
                # 宽表：每行一期，列为指标名（含东财英文字段 REPORT_DATE, ROEJQ 等）
                period_col = next((c for c in ["REPORT_DATE", "报告期", "date", "报告日期"] if c in df.columns), None)
                if period_col:
                    df = df.sort_values(period_col, ascending=False)
                # 优先取年报（REPORT_DATE 末四位 1231），与东财页面展示一致
                row = None
                if "REPORT_DATE" in df.columns:
                    rd_ser = df["REPORT_DATE"].astype(str)
                    year_end_mask = rd_ser.str.endswith("1231", na=False)
                    if year_end_mask.any():
                        row = df.loc[year_end_mask].iloc[0]  # 取最新年报行（已按 REPORT_DATE 降序）
                    if row is None:
                        row = df.iloc[0]
                else:
                    row = df.iloc[0]
                for k in ["REPORT_DATE", "报告期", "date", "报告日期"]:
                    if k in row.index:
                        report_period = str(row.get(k))
                        break

                def _pick(keys: list[str]):
                    for col, val in row.items():
                        if any(k in str(col) for k in keys):
                            return val
                    return None

                pe = _pick(["市盈率", "PE", "pe", "动态市盈率"])
                pb = _pick(["市净率", "PB", "pb"])
                roe = _pick(["净资产收益率", "ROE", "净资产报酬率"])
                rev_g = _pick(["营业收入同比", "收入同比", "营收同比", "营业收入增长率", "营业收入同比增长"])
                prof_g = _pick(["净利润同比", "利润同比", "净利润增长率", "净利润同比增长"])

                # 东财接口返回英文字段：ROEJQ/PARENTNETPROFITTZ/TOTALOPERATEREVETZ 等（单位均为%）
                if (roe is None or rev_g is None or prof_g is None) and "REPORT_DATE" in df.columns:
                    em_roe, em_rev_g, em_prof_g = _parse_em_finance_row(row)
                    if roe is None:
                        roe = em_roe
                    if rev_g is None:
                        rev_g = em_rev_g
                    if prof_g is None:
                        prof_g = em_prof_g
                    # 若年报行缺营收/利润增速，用最近一期（季报）补
                    if (rev_g is None or prof_g is None) and len(df) > 1:
                        latest_row = df.iloc[0]
                        if not (row is not None and latest_row.equals(row)):
                            em2_roe, em2_rev_g, em2_prof_g = _parse_em_finance_row(latest_row)
                            if rev_g is None:
                                rev_g = em2_rev_g
                            if prof_g is None:
                                prof_g = em2_prof_g

            # 若仍全为空，尝试按列名模糊匹配（兼容不同数据源列名）
            if pe is None and pb is None and roe is None and rev_g is None and prof_g is None:
                row = df.iloc[0] if "报告期" in df.columns else df.iloc[-1]
                for col in row.index:
                    c = str(col)
                    v = row.get(col)
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        continue
                    if ("市盈" in c or "pe" in c.lower()) and pe is None:
                        pe = v
                    elif ("市净" in c or "pb" in c.lower()) and pb is None:
                        pb = v
                    elif ("净资产收益" in c or "roe" in c.lower()) and roe is None:
                        roe = v
                    elif (("收入" in c and "同比" in c) or ("营收" in c and "增" in c)) and rev_g is None:
                        rev_g = v
                    elif ("净利润" in c and ("同比" in c or "增" in c)) and prof_g is None:
                        prof_g = v

        # ROE/营收增速/利润增速 主数据源未解析到时，从新浪摘要与东财同行比较接口补数
        if roe is None or rev_g is None or prof_g is None:
            # 首先尝试从已获取的 df 中提取（如果是新浪摘要格式）
            if df is not None and not df.empty and "指标" in df.columns:
                rev_g_new, prof_g_new = _extract_growth_from_abstract(df)
                if rev_g is None and rev_g_new is not None:
                    rev_g = rev_g_new
                if prof_g is None and prof_g_new is not None:
                    prof_g = prof_g_new

            # 如果还是缺失，调用备用接口
            if roe is None or rev_g is None or prof_g is None:
                roe_fb, rev_g_fb, prof_g_fb = _fetch_roe_revg_profg_fallback(symbol)
                if roe is None:
                    roe = roe_fb
                if rev_g is None:
                    rev_g = rev_g_fb
                if prof_g is None:
                    prof_g = prof_g_fb

        # 财务接口无数据或缺少 PE/PB 时，从行情兜底取市盈率、市净率
        pe_spot, pb_spot = _get_pe_pb_from_spot(symbol)
        if pb_spot == "N/A" and hasattr(ak, "stock_zh_valuation_comparison_em"):
            try:
                em_sym = _to_em_symbol(symbol).upper()
                vdf = _fetch_valuation_comparison(symbol=em_sym)
                if vdf is not None and not vdf.empty:
                    for col in ("市净率-MRQ", "市净率-24A", "市净率"):
                        if col in vdf.columns:
                            v = vdf.iloc[0].get(col)
                            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                                pb_spot = str(round(float(v), 2))
                                break
            except Exception:
                pass
        if (pe is None or str(pe) == "nan") and (pb is None or str(pb) == "nan"):
            if pe_spot != "N/A" or pb_spot != "N/A":
                header = f"股票 {symbol} 核心财务指标（估值来自行情）\n"
                header += f"  市盈率(动态) PE: {pe_spot}\n"
                header += f"  市净率 PB: {pb_spot}\n"
                if roe is not None or rev_g is not None or prof_g is not None:
                    header += f"  净资产收益率 ROE: {_fmt_finance_val(roe, as_pct=True)}\n"
                    header += f"  营业收入同比增速: {_fmt_finance_val(rev_g, as_pct=True)}\n"
                    header += f"  净利润同比增速: {_fmt_finance_val(prof_g, as_pct=True)}\n"
                else:
                    header += "  （财报类指标 ROE/营收与利润增速 当前数据源暂不可用，可稍后再试或结合行情做估值参考。）"
                return header
        elif pe is None or str(pe) == "nan":
            pe = pe_spot if pe_spot != "N/A" else None
        elif pb is None or str(pb) == "nan":
            pb = pb_spot if pb_spot != "N/A" else None

        # 无可用数据时：df 为空，或 df 有表但解析后五项全为空，均走行情/个股信息兜底
        no_usable_from_df = (
            df is None
            or df.empty
            or (
                pe is None
                and pb is None
                and roe is None
                and rev_g is None
                and prof_g is None
            )
        )
        if no_usable_from_df:
            if pe_spot != "N/A" or pb_spot != "N/A":
                header = f"股票 {symbol} 核心财务指标（估值来自行情/个股信息）\n"
                header += f"  市盈率(动态) PE: {pe_spot}\n"
                header += f"  市净率 PB: {pb_spot}\n"
                header += "  （财报类指标 ROE/营收与利润增速 当前数据源暂不可用，可稍后再试或结合行情做估值参考。）"
                return header
            return (
                f"暂时无法获取股票 {symbol} 的财务分析指标数据（可能尚未披露或数据源不可用）。\n\n"
                "提示：你可以改用市值、市盈率等简单指标进行大致估值，或稍后再试。"
            )

        # 报告期格式化为 YYYY-MM-DD，并标注年报/季报
        period_label = ""
        if report_period:
            s = str(report_period).strip()
            if len(s) >= 8 and s[:8].isdigit():
                period_label = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
                if s.endswith("1231"):
                    period_label += "（年报）"
                else:
                    period_label += "（报告期）"
        header = f"股票 {symbol} 核心财务指标"
        if period_label:
            header += f"（{period_label}）"
        header += ":\n"

        output = header
        output += f"  市盈率 PE: {_fmt(pe)}\n"
        output += f"  市净率 PB: {_fmt(pb)}\n"
        output += f"  净资产收益率 ROE: {_fmt_finance_val(roe, as_pct=True)}\n"
        output += f"  营业收入同比增速: {_fmt_finance_val(rev_g, as_pct=True)}\n"
        output += f"  净利润同比增速: {_fmt_finance_val(prof_g, as_pct=True)}\n"
        output += "\n以上指标可用于基本面的估值与成长性分析。"
        return output
    except Exception as e:
        return f"获取核心财务指标失败: {str(e)[:200]}"


@tool
def search_stock(keyword: str) -> str:
    """
    根据关键词搜索股票。

    Args:
        keyword: 搜索关键词，可以是股票名称或代码的一部分

    Returns:
        匹配的股票列表
    """
    try:
        kw = (keyword or "").strip()
        if not kw:
            return (
                "请输入搜索关键词（股票名称或代码的一部分）。\n\n"
                "示例: 平安、茅台、600519、000001"
            )

        # 搜索默认用「代码+名称列表」（更快、更稳定）；实时行情需要时再用 get_stock_realtime 查单只
        df = _get_stock_list_code_name_cached()
        list_only = True
        if df.empty:
            # 兜底：代码列表也失败时再尝试全市场行情（可能较慢/易断连）
            df = _fetch_stock_spot()
            list_only = False
            if df.empty:
                return (
                    "暂时无法获取股票列表/行情数据，请稍后重试。\n\n"
                    "也可直接使用 6 位代码查询，如: 000001、600519、300750"
                )

        # 确保用于筛选的列存在且为字符串，避免 代码 为数值时 .str 报错
        if "代码" not in df.columns or "名称" not in df.columns:
            # 兜底：尝试从全市场行情里搜索（可能较慢，但列名一般规范）
            try:
                df2 = _fetch_stock_spot()
                if not df2.empty and "代码" in df2.columns and "名称" in df2.columns:
                    df = df2
                    list_only = False
                else:
                    cols = ", ".join([str(c) for c in list(df.columns)[:8]])
                    return (
                        "暂时无法解析股票列表数据格式，无法完成搜索。\n\n"
                        f"当前返回列(部分): {cols}\n\n"
                        "建议：直接用 6 位股票代码查询，或稍后重试。"
                    )
            except Exception:
                cols = ", ".join([str(c) for c in list(df.columns)[:8]])
                return (
                    "暂时无法获取/解析股票列表数据，无法完成搜索。\n\n"
                    f"当前返回列(部分): {cols}\n\n"
                    "建议：直接用 6 位股票代码查询，或稍后重试。"
                )

        code_ser = df["代码"].astype(str).str.replace(r"\D", "", regex=True)
        # 代码统一为 6 位便于匹配：用户搜 "1" 或 "000001" 都能命中
        code_ser = code_ser.str.zfill(6)
        name_ser = df["名称"].astype(str).fillna("")
        kw_clean = kw.replace(" ", "")
        mask = (
            code_ser.str.contains(kw_clean, case=False, na=False)
            | name_ser.str.contains(kw, case=False, na=False)
        )
        result_df = df.loc[mask]

        # 只选取存在的列，避免 KeyError（代码列表通常只有 代码/名称）
        out_cols = [c for c in ["代码", "名称", "最新价", "涨跌幅"] if c in result_df.columns]
        if not out_cols:
            return f"未找到与 '{kw}' 相关的股票。请检查关键词或改用 6 位代码查询。"
        result_df = result_df[out_cols].head(20)

        if result_df.empty:
            return (
                f"未找到与 '{kw}' 相关的股票。\n\n"
                f"提示: 请用 6 位数股票代码查询，例如 000001、600519、300750"
            )
        header = f"搜索 '{kw}' 的结果（前20个）"
        if list_only:
            header += "（快速匹配：仅代码与名称；需要实时价格请用 get_stock_realtime）"
        return f"{header}:\n\n{format_dataframe(result_df)}"
    except Exception as e:
        return f"搜索股票失败: {str(e)[:200]}\n\n建议直接使用 6 位股票代码查询"


@tool
def search_stock_any(keyword: str) -> str:
    """
    智能搜索 A股、港股股票。

    当用户只说“搜索股票”或不指定市场时，推荐优先使用本工具：
    - 能自动根据关键词特征判断更可能的市场
    - 若无法确定，会依次尝试 A股 -> 港股，只要有结果就返回

    Args:
        keyword: 搜索关键词，可以是股票名称或代码的一部分

    Returns:
        匹配的股票列表，并在可能时标注来源市场
    """
    try:
        kw = (keyword or "").strip()
        if not kw:
            return (
                "请输入搜索关键词（股票名称或代码的一部分）。\n\n"
                "示例: 平安、茅台、600519、00700、AAPL"
            )

        kw_upper = kw.upper()
        is_digits = kw.isdigit()

        def _call_a() -> str:
            return _invoke_sub_tool(search_stock, {"keyword": kw})

        def _call_hk() -> str:
            return _invoke_sub_tool(search_stock_hk, {"keyword": kw})

        order: list[tuple[str, Callable[[], str]]] = []

        # 简单规则判断优先市场
        if is_digits and len(kw) == 6:
            # 6 位纯数字更像 A 股
            order = [("A股", _call_a), ("港股", _call_hk)]
        elif is_digits and len(kw) == 5:
            # 5 位纯数字更像港股
            order = [("港股", _call_hk), ("A股", _call_a)]
        elif kw_upper.startswith("HK") or "港股" in kw or "HK:" in kw_upper:
            order = [("港股", _call_hk), ("A股", _call_a)]
        elif any(tag in kw_upper for tag in ["US:", "NASDAQ", "NYSE"]):
            # 当前版本不再支持美股数据，直接提示
            return (
                "当前版本暂不支持美股数据查询。\n\n"
                "请使用 A股或港股代码/名称进行搜索，例如 A股 600519、港股 00700。"
            )
        elif re.match(r"^[A-Z][A-Z0-9\.\-]{0,10}$", kw_upper):
            # 纯英文代码，当前版本不支持美股
            return (
                "检测到可能为美股代码，但当前版本暂不支持美股数据查询。\n\n"
                "请使用 A股或港股代码/名称进行搜索，例如 A股 600519、港股 00700。"
            )
        else:
            # 自然语言或模糊关键词，默认先试 A 股
            order = [("A股", _call_a), ("港股", _call_hk)]

        last_msg = ""

        for market_name, fn in order:
            try:
                msg = fn()
            except Exception as e:
                err = str(e)
                if "not callable" in err.lower() or "StructuredTool" in err:
                    last_msg = f"{market_name} 搜索暂时不可用，请使用上方 A 股结果或直接输入 6 位代码（如 600519）查询。"
                else:
                    last_msg = f"{market_name} 搜索失败: {err[:120]}"
                continue

            # 若返回的是明显的“未找到”提示，则继续尝试其它市场
            if "未找到与" in msg and "相关的" in msg:
                last_msg = msg
                continue
            # 明确的数据源故障/超时提示，也尝试其它市场
            if "无法获取" in msg or "超时" in msg:
                last_msg = msg
                continue

            # 命中有效结果，附带来源市场标注（若原文中尚未包含）
            if (
                "搜索 '" in msg
                and "的结果" in msg
                and "（前20个）" in msg
                and "（来源：" not in msg
            ):
                return msg + f"\n\n（来源：{market_name}）"
            return msg

        if last_msg:
            return last_msg

        return (
            f"未在 A股、港股中找到与 '{kw}' 相关的股票。\n\n"
            "提示: 也可以直接使用具体代码查询，例如 A股 600519、港股 00700。"
        )
    except Exception as e:
        return f"搜索股票失败: {str(e)[:200]}"


@tool
def get_stock_news(symbol: str) -> str:
    """
    获取个股新闻资讯。

    Args:
        symbol: 股票代码，如 "000001"

    Returns:
        最近的新闻标题和时间
    """
    try:
        symbol = validate_stock_code(symbol)
        df = _fetch_stock_news(symbol)

        if df.empty:
            return f"未找到股票 {symbol} 的相关新闻"

        # Select relevant columns and limit results
        result_df = df.head(10)
        output = f"股票 {symbol} 最新新闻:\n\n"
        for _, row in result_df.iterrows():
            output += f"- [{row.get('发布时间', 'N/A')}] {row.get('新闻标题', 'N/A')}\n"
        return output
    except Exception as e:
        return f"获取新闻失败: {str(e)[:200]}"


@tool
def get_hot_stocks() -> str:
    """
    获取当前热门股票排行。

    Returns:
        热门股票列表，按人气排名
    """
    try:
        df = _fetch_hot_stocks()

        if df.empty:
            return "暂无热门股票数据"

        # Select available columns dynamically
        preferred_cols = ["排名", "序号", "代码", "股票代码", "名称", "股票名称", "最新价", "涨跌幅"]
        available_cols = [c for c in preferred_cols if c in df.columns]
        if not available_cols:
            available_cols = list(df.columns[:5])

        result_df = df.head(20)[available_cols]
        return f"热门股票排行:\n\n{format_dataframe(result_df)}"
    except Exception as e:
        return f"获取热门股票失败: {str(e)[:200]}"


@tool
def get_industry_boards() -> str:
    """
    获取行业板块列表及行情。

    Returns:
        行业板块列表，包括涨跌幅和领涨股
    """
    try:
        df = _fetch_industry_boards()

        if df.empty:
            return (
                "❌ 无法获取行业板块数据\n\n"
                "可能原因：\n"
                "1. 当前时段非交易时间\n"
                "2. 数据源接口临时不可用\n"
                "3. 网络连接问题\n\n"
                "💡 建议：\n"
                "- 改为查询具体股票\n"
                "- 稍后再试"
            )

        # Sort by change percentage
        if "涨跌幅" in df.columns:
            df = df.sort_values("涨跌幅", ascending=False)

        result_df = df.head(20)
        return f"行业板块排行:\n\n{format_dataframe(result_df)}"
    except Exception as e:
        return (
            f"❌ 获取行业板块失败\n\n"
            f"错误信息: {str(e)[:150]}\n\n"
            f"💡 建议：改为查询具体股票或稍后重试"
        )


@tool
def get_industry_board_detail(industry_name: str) -> str:
    """
    获取指定行业板块的整体涨跌幅及行业平均估值（PE、PB）。

    用于回答某行业（如白酒、酿酒、食品饮料、新能源）的整体走势与估值水平。
    先根据关键词匹配行业名称，再返回该板块指数涨跌幅、领涨股及成分股平均市盈率/市净率。

    Args:
        industry_name: 行业名称或关键词，如 "白酒"、"酿酒"、"食品饮料"、"新能源"、"电池"

    Returns:
        该行业板块的整体涨跌幅、领涨股、成分股数量及行业平均 PE/PB
    """
    try:
        name = (industry_name or "").strip()
        if not name:
            return "请输入行业名称或关键词，例如：白酒、酿酒、食品饮料、新能源、电池。可先调用 get_industry_boards 查看全部行业板块名称。"

        def _industry_fallback_msg(keyword: str) -> str:
            return (
                "暂时无法获取行业板块列表（东财/同花顺接口连接异常或限流）。\n\n"
                "💡 建议：\n"
                "- 先查询具体股票，如 贵州茅台(600519)、五粮液 等了解个股行情\n"
                "- 稍后重试 get_industry_boards 或 get_industry_board_detail\n"
                f"- 白酒相关在列表中多为「酿酒行业」，可恢复后搜「酿酒」"
            )

        try:
            df = _fetch_industry_boards()
        except Exception:
            return _industry_fallback_msg(name)
        if df.empty:
            return _industry_fallback_msg(name)

        # 板块名称列可能为 "板块名称" 或 "行业名称" 等
        name_col = None
        for col in df.columns:
            if "名称" in str(col) and ("板块" in str(col) or "行业" in str(col)):
                name_col = col
                break
        if name_col is None:
            name_col = "板块名称" if "板块名称" in df.columns else df.columns[0]

        names = df[name_col].astype(str).str.strip()
        # 常见别名（东方财富板块名称多为「XX行业」）
        alias = {"白酒": "酿酒", "锂电": "能源金属", "光伏": "光伏设备", "芯片": "半导体"}
        search_name = alias.get(name, name)
        # 精确匹配
        match = names.str.lower() == search_name.lower()
        if not match.any():
            # 模糊匹配：关键词包含在板块名称中
            match = names.str.contains(search_name, case=False, na=False)
        if not match.any():
            match = names.str.contains(name, case=False, na=False)
        if not match.any():
            return (
                f"未找到与「{name}」匹配的行业板块。\n\n"
                "请先调用 get_industry_boards 查看完整行业列表，或使用更通用的关键词（如 酿酒、食品饮料、电池）。"
            )

        row = df.loc[match].iloc[0]
        board_name = str(row.get(name_col, name))
        # 东方财富成分股接口需使用精确的板块名称
        code_col = "板块代码" if "板块代码" in df.columns else None
        board_code = str(row[code_col]) if code_col and code_col in row.index else ""

        change = row.get("涨跌幅", "N/A")
        latest = row.get("最新价", "N/A")
        leader = row.get("领涨股票", row.get("领涨股", "N/A"))
        leader_change = row.get("领涨股票-涨跌幅", row.get("领涨股-涨跌幅", ""))

        avg_pe = None
        avg_pb = None
        cons_count = 0
        cons_df = None
        try:
            cons_df = _fetch_industry_cons_em(board_name)
        except Exception:
            pass
        if cons_df is not None and not cons_df.empty:
            cons_count = len(cons_df)
            pe_col = None
            pb_col = None
            for c in cons_df.columns:
                if "市盈" in str(c) or "PE" in str(c):
                    pe_col = c
                if "市净" in str(c) or "PB" in str(c):
                    pb_col = c
            if pe_col:
                vals = pd.to_numeric(cons_df[pe_col], errors="coerce").dropna()
                vals = vals[vals > 0][vals < 1e5]
                if not vals.empty:
                    avg_pe = round(vals.mean(), 2)
            if pb_col:
                vals = pd.to_numeric(cons_df[pb_col], errors="coerce").dropna()
                vals = vals[vals > 0][vals < 1e4]
                if not vals.empty:
                    avg_pb = round(vals.mean(), 2)

        def _fmt_num(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return "N/A"
            if isinstance(v, (int, float)):
                return f"{v}%"
            return str(v)

        lines = [
            f"行业板块：{board_name}",
            f"板块整体涨跌幅：{_fmt_num(change) if isinstance(change, (int, float)) else change}",
            f"板块最新价：{latest}",
            f"领涨股票：{leader} {leader_change}%" if leader_change != "" and leader_change != "N/A" else f"领涨股票：{leader}",
            f"成分股数量：{cons_count}",
        ]
        if avg_pe is not None:
            lines.append(f"行业平均市盈率（PE）：{avg_pe}")
        if avg_pb is not None:
            lines.append(f"行业平均市净率（PB）：{avg_pb}")
        if avg_pe is None and avg_pb is None and cons_count > 0:
            lines.append("（成分股 PE/PB 暂未统计，部分标的可能无估值数据）")
        if cons_count == 0 and (avg_pe is None and avg_pb is None):
            lines.append("（行业平均估值因网络波动暂时无法获取，请稍后再试或仅参考上方板块涨跌幅与领涨股）")

        return "\n".join(lines)
    except Exception as e:
        return f"获取行业板块详情失败: {str(e)[:200]}"


@tool
def get_concept_boards() -> str:
    """
    获取概念板块列表及行情。

    Returns:
        概念板块列表，包括涨跌幅和领涨股
    """
    try:
        df = _fetch_concept_boards()

        if df.empty:
            return (
                "❌ 无法获取概念板块数据\n\n"
                "可能原因：\n"
                "1. 当前时段非交易时间\n"
                "2. 数据源接口临时不可用\n"
                "3. 网络连接问题\n\n"
                "💡 建议：\n"
                "- 改为查询具体股票\n"
                "- 稍后再试"
            )

        # Sort by change percentage
        if "涨跌幅" in df.columns:
            df = df.sort_values("涨跌幅", ascending=False)

        # 返回较多条以便「AI概念」等推荐场景能命中相关板块（如 人工智能、ChatGPT概念）
        result_df = df.head(50)
        return f"概念板块排行:\n\n{format_dataframe(result_df)}"
    except Exception as e:
        return (
            f"❌ 获取概念板块失败\n\n"
            f"错误信息: {str(e)[:150]}\n\n"
            f"💡 建议：改为查询具体股票或稍后重试"
        )


@tool
def get_concept_stocks(concept_name: str) -> str:
    """
    带整体超时保护的外层工具封装，避免在网络异常时卡住整轮思考。
    """
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_get_concept_stocks_impl, concept_name)
            return future.result(timeout=CONCEPT_STOCKS_TOTAL_TIMEOUT)
    except FutureTimeoutError:
        return (
            "获取概念成分股超时，数据源响应过慢或网络不稳定。\n\n"
            "建议：\n"
            "- 先调用 get_concept_boards 查看板块列表，确认板块代码(BK 开头) 后再查；\n"
            "- 或稍后重试，必要时缩小概念范围，例如改用具体细分概念名称。"
        )
    except Exception as e:
        err = str(e)[:200]
        if "板块名称" in err or "values" in err or "KeyError" in err or "IndexError" in err:
            return (
                f"未找到概念「{concept_name}」。请先调用 get_concept_boards 查看准确板块名称（如：人工智能、ChatGPT概念）后再试。"
            )
        return f"获取概念成分股失败: {err}"
