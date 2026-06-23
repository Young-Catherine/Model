import gurobipy as gp
from gurobipy import GRB
import matplotlib.pyplot as plt
import numpy as np
import argparse
import csv
import json
from pathlib import Path

def plot_feasible_region(m, P, H, u, unit_params, output_path=None, show=True):
    """
    绘制CHP机组的热电可行域与实际调度轨迹
    该函数需在 m.optimize() 且求解成功后调用
    """
    # 提取参数
    P_max = unit_params["P_max"]
    P_min = unit_params["P_min"]
    H_max = unit_params["H_max"]
    c_v = unit_params["c_v"]
    alpha = unit_params["alpha"]
    P_m = unit_params["P_m"]
    T = len(P)

    # ==========================================
    # 1. 计算理论边界 (使用 numpy 向量化计算)
    # ==========================================
    h_vals = np.linspace(0, H_max, 200)
    
    # 边界1：背压上限线
    p_ceil = P_max - c_v * h_vals
    # 边界2：背压下限线
    p_floor_1 = P_min - c_v * h_vals
    # 边界3：抽汽最小发电线
    p_floor_2 = alpha * h_vals + P_m
    
    # 实际下边界是边界2和边界3的极大值
    p_floor = np.maximum(p_floor_1, p_floor_2)

    # ==========================================
    # 2. 提取求解器实际运行结果
    # ==========================================
    h_actual = []
    p_actual = []
    t_labels = []
    
    for t in range(T):
        if u[t].X > 0.5:  # 只绘制开机状态的点
            h_actual.append(H[t].X)
            p_actual.append(P[t].X)
            t_labels.append(t)

    # ==========================================
    # 3. Matplotlib 绘图
    # ==========================================
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # 绘制可行域阴影
    ax.fill_between(h_vals, p_floor, p_ceil, color='#87CEFA', alpha=0.3, label='理论安全运行区间')
    
    # 绘制边界辅助线
    ax.plot(h_vals, p_ceil, 'r--', linewidth=2, label='背压上限 ')
    ax.plot(h_vals, p_floor_1, 'b:', linewidth=2, label='背压下限')
    ax.plot(h_vals, p_floor_2, 'g:', linewidth=2, label='最小凝汽下限')
    ax.axvline(x=H_max, color='purple', linestyle='--', linewidth=2, label='供热能力上限')

    # 绘制实际调度散点（按时间使用色带渐变，越晚颜色越亮/深）
    scatter = ax.scatter(h_actual, p_actual, c=t_labels, cmap='plasma', 
                         s=100, edgecolor='black', zorder=5, label='实际出清调度点')
    
    # 添加时刻文本标签
    for i, txt in enumerate(t_labels):
        ax.annotate(f"{txt}:00", (h_actual[i], p_actual[i]), 
                    textcoords="offset points", xytext=(8,8), ha='center', fontsize=9)

    # 添加颜色条指示时间
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('调度时刻 (时)', rotation=270, labelpad=15)

    # 图表修饰
    ax.set_xlim(0, H_max * 1.1)
    ax.set_ylim(0, P_max * 1.1)
    ax.set_xlabel('热出力 H (MWth)', fontsize=12)
    ax.set_ylabel('电出力 P (MW)', fontsize=12)
    ax.set_title('CHP机组日前调度热电可行域与实际轨迹验证', fontsize=14, fontweight='bold')
    ax.legend(loc='lower right')
    ax.grid(True, linestyle='-.', alpha=0.5)

    plt.tight_layout()
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=180, bbox_inches="tight")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig

def run_chp_optimization(
    plot=True,
    export_dir=None,
    strict_heat=True,
    allow_heat_over_supply=False,
):

    # ============================================================
    # 1: 参数配置（后续替换实际数据）
    # ============================================================

    # --- 1.1 机组物理参数 【待替换：实际DCS/设计规范值】 ---
    unit_params = {
        "P_max"          : 300.0,  # 额定最大电出力 [MW]   【待替换】
        "P_min"          : 120.0,  # 纯凝最小电出力 [MW]   【待替换】
        "H_max"          : 270.0,  # 最大供热能力 [MWth]  【待替换】
        "c_v"            : 0.15,   # 热电比（背压线斜率）[MW/MWth]  【待替换】
        "alpha"          : 0.5,    # 抽汽影响系数 [MW/MWth]          【待替换】
        "P_m"            : 50.0,   # 最大抽汽工况下最小电出力 [MW]   【待替换】
        "ramp_rate"      : 90.0,   # 最大爬坡速率 [MW/h]             【待替换】
        "T_on_min"       : 6,      # 最小连续运行时间 [h]            【待替换】
        "T_off_min"      : 6,      # 最小连续停机时间 [h]            【待替换】
        "P_init"         : 200.0,  # 初始电出力（上一调度周期末值）[MW] 【待替换】
        "u_init"         : 1,      # 初始运行状态（1=运行，0=停机）
        "on_hours_init"  : 10,     # 已连续运行小时数（用于MUT初始化）【待替换】
        "off_hours_init" : 0,      # 已连续停机小时数（用于MDT初始化）【待替换】
    }

    # --- 1.2 煤耗/燃料成本参数 【待替换：实际热试验/设计煤耗曲线】 ---
    cost_params = {
        "a_cost"   : 0.03,      # 煤耗曲线二次项系数 [元/MW²]  【待替换】
        "b_cost"   : 180.0,     # 煤耗曲线一次项系数 [元/MW]   【待替换】
        "h_cost"   : 18.0,      # 供热边际燃料成本 [元/GJ]       【待替换】
        "c_cost"   : 10000.0,   # 空载固定煤耗 [元/h]          【待替换】
        "C_start"  : 50000.0,   # 单次启动成本 [元]            【待替换】
        "C_shut"   : 5000.0,    # 单次停机成本 [元]            【待替换】
        "lambda_h" : 20.0,      # 供热价格 [元/GJ]             【待替换】
    }

    # --- 1.3 碳排放参数 【待替换：CEMS实测数据 + 主管部门政策文件】 ---
    carbon_params = {
        "carbon_price" : 120.0,  # 碳市场均价 [元/吨CO₂]               【待替换】
        "mu_e"         : 0.85,   # 供电实际碳排强度 [吨CO₂/MWh]         【待替换】
        "mu_h"         : 0.11,   # 供热实际碳排强度 [吨CO₂/GJ_heat]     【待替换】
        "eta_e"        : 0.80,   # 供电免费配额基准 [吨CO₂/MWh]（政策值）【待替换】
        "eta_h"        : 0.10,   # 供热免费配额基准 [吨CO₂/GJ]（政策值） 【待替换】
        "mwth_to_gj"   : 3.6,    # 单位换算：1 MWth·h = 3.6 GJ
    }

    # --- 1.4 现货电价时序 [元/MWh] 【待替换：电力交易中心实际出清价格】 ---
    # 当前为理论构造的冬季风电反调峰曲线（非实测！）
    lambda_e = [  0.0,   0.0,   20.0,  20.0,  30.0,  30.0,  50.0, 150.0,
                300.0, 350.0, 250.0, 200.0, 200.0, 200.0, 250.0, 300.0,
                400.0, 600.0, 800.0, 750.0, 500.0, 300.0, 100.0,  50.0]

    # --- 1.5 热负荷需求时序 [MWth] 【待替换：热网实测/气象预测数据】 ---
    # 当前为简化曲线：白天供热需求高，夜间稍低，机组有一定灵活性
    H_demand = [150.0, 150.0, 140.0, 140.0, 150.0, 160.0, 170.0, 180.0,
                180.0, 180.0, 175.0, 170.0, 165.0, 165.0, 170.0, 175.0,
                180.0, 185.0, 190.0, 185.0, 180.0, 170.0, 160.0, 155.0]

    T = 24  # 调度时段数（小时）

    # ============================================================
    # 2: 解包参数
    # ============================================================
    P_max          = unit_params["P_max"]
    P_min          = unit_params["P_min"]
    H_max          = unit_params["H_max"]
    c_v            = unit_params["c_v"]
    alpha          = unit_params["alpha"]
    P_m            = unit_params["P_m"]
    ramp_rate      = unit_params["ramp_rate"]
    T_on_min       = unit_params["T_on_min"]
    T_off_min      = unit_params["T_off_min"]
    P_init         = unit_params["P_init"]
    u_init         = unit_params["u_init"]
    on_hours_init  = unit_params["on_hours_init"]
    off_hours_init = unit_params["off_hours_init"]

    a_cost   = cost_params["a_cost"]
    b_cost   = cost_params["b_cost"]
    h_cost   = cost_params["h_cost"]
    c_cost   = cost_params["c_cost"]
    C_start  = cost_params["C_start"]
    C_shut   = cost_params["C_shut"]
    lambda_h = cost_params["lambda_h"]

    carbon_price = carbon_params["carbon_price"]
    mu_e         = carbon_params["mu_e"]
    mu_h         = carbon_params["mu_h"]
    eta_e        = carbon_params["eta_e"]
    eta_h        = carbon_params["eta_h"]
    mwth_to_gj   = carbon_params["mwth_to_gj"]

    # ============================================================
    # 3: 建立 Gurobi 模型（MIQP）
    # ============================================================
    m = gp.Model("300MW_CHP_Dispatch_v2")
    m.setParam('OutputFlag', 0)
    m.setParam('MIPGap', 1e-4)       # 相对最优性间隙
    m.setParam('TimeLimit', 120)     # 最长求解时间 [秒]

    # ============================================================
    # 4: 决策变量
    # ============================================================
    P = m.addVars(T, lb=0, ub=P_max, vtype=GRB.CONTINUOUS, name="P")  # 电出力 [MW]
    H = m.addVars(T, lb=0, ub=H_max, vtype=GRB.CONTINUOUS, name="H")  # 热出力 [MWth] ← v2新增
    u = m.addVars(T, vtype=GRB.BINARY, name="u")   # 运行状态 (1=运行)
    v = m.addVars(T, vtype=GRB.BINARY, name="v")   # 启动动作 (1=本时段启动)
    w = m.addVars(T, vtype=GRB.BINARY, name="w")   # 停机动作 (1=本时段停机)

    # 辅助变量：HU[t] = H[t] × u[t]（McCormick线性化）
    # 物理含义：机组运行时等于实际热出力，停机时强制为零
    HU = m.addVars(T, lb=0.0, ub=H_max, vtype=GRB.CONTINUOUS, name="HU")

    # ============================================================
    # 5: 约束条件
    # ============================================================

    # ---- 5.1 启停逻辑约束 ----
    for t in range(T):
        prev_u = u_init if t == 0 else u[t - 1]
        m.addConstr(v[t] - w[t] == u[t] - prev_u,  name=f"logic_{t}")
        m.addConstr(v[t] + w[t] <= 1,               name=f"excl_{t}")

    # ---- 5.2 最小连续运行时间约束（MUT）----
    # 初始已运行时段的强制运行：若已运行不足 T_on_min 小时
    remaining_on = max(0, T_on_min - on_hours_init) if u_init == 1 else 0
    for t in range(min(remaining_on, T)):
        m.addConstr(u[t] == 1, name=f"MUT_init_{t}")

    # 新启动触发的最小运行时间
    for t in range(T):
        for k in range(t, min(t + T_on_min, T)):
            m.addConstr(u[k] >= v[t], name=f"MUT_{t}_{k}")

    # ---- 5.3 最小连续停机时间约束（MDT）----
    # 初始已停机时段的强制停机
    remaining_off = max(0, T_off_min - off_hours_init) if u_init == 0 else 0
    for t in range(min(remaining_off, T)):
        m.addConstr(u[t] == 0, name=f"MDT_init_{t}")

    # 新停机触发的最小停机时间
    for t in range(T):
        for k in range(t, min(t + T_off_min, T)):
            m.addConstr(1 - u[k] >= w[t], name=f"MDT_{t}_{k}")

    # ---- 5.4 供热需求约束 ----
    for t in range(T):
        if strict_heat:
            # 甲方收益测算默认要求热负荷必须由本机组满足，避免停机缺热仍被视为可行。
            m.addConstr(H[t] >= H_demand[t], name=f"H_lb_{t}")
        else:
            # 非严格模式用于演示：机组运行时才要求满足热负荷。
            m.addConstr(H[t] >= H_demand[t] * u[t], name=f"H_lb_{t}")
        if not allow_heat_over_supply:
            # 基准验证按热负荷结算，不允许为了热收益无依据地超供热。
            m.addConstr(H[t] <= H_demand[t], name=f"H_eq_{t}")
        # 机组停机时，热出力为零（辅助热源保障不在本模型内建模）
        m.addConstr(H[t] <= H_max * u[t],        name=f"H_ub_{t}")

    # ---- 5.5 热电联产可行域约束----
    for t in range(T):
        # 背压上限线：P ≤ P_max - c_v·H（供热越多，可发电上限越低）
        m.addConstr(P[t] + c_v * H[t] <= P_max * u[t], name=f"feas_ceil_{t}")
        # 背压下限线：P ≥ P_min - c_v·H（供热可以"替代"部分最低发电量）
        m.addConstr(P[t] + c_v * H[t] >= P_min * u[t], name=f"feas_floor_{t}")
        # HU[t] = H[t] × u[t] 的 McCormick 精确线性化（4条）
        m.addConstr(HU[t] <= H_max * u[t],               name=f"mc_ub_{t}")   # u=0→HU=0
        m.addConstr(HU[t] <= H[t],                        name=f"mc_h_{t}")    # HU不超过H
        m.addConstr(HU[t] >= H[t] - H_max * (1 - u[t]), name=f"mc_lb_{t}")   # u=1→HU=H
        # lb=0 已由变量下界保证，第4条无需显式添加

        # 抽汽最小发电线（已线性化）
        m.addConstr(P[t] >= alpha * HU[t] + P_m * u[t],  name=f"feas_steam_{t}")

    # ---- 5.6 爬坡约束（含初始时刻）----[实际机组冷/温/热启动后出力爬升需要时间待完善]
    # t=0：与调度前末态 P_init 比较
    m.addConstr(P[0] - P_init <= ramp_rate * u_init + P_max * v[0], name="ramp_up_0")
    m.addConstr(P_init - P[0] <= ramp_rate * u[0] + P_max * w[0],   name="ramp_dn_0")
    for t in range(1, T):
        m.addConstr(P[t] - P[t-1] <= ramp_rate * u[t-1] + P_max * v[t], name=f"ramp_up_{t}")
        m.addConstr(P[t-1] - P[t] <= ramp_rate * u[t]   + P_max * w[t], name=f"ramp_dn_{t}")

    # ============================================================
    # 6: 目标函数（最大化全天净收益）
    # ============================================================

    # 电能收益
    revenue_e = gp.quicksum(P[t] * lambda_e[t] for t in range(T))

    # 供热收益
    revenue_h = gp.quicksum(H[t] * lambda_h * mwth_to_gj for t in range(T))

    # 燃料（煤耗）成本：电侧二次型煤耗曲线 + 供热边际燃料成本
    fuel_cost = gp.quicksum(
        a_cost * P[t] * P[t]
        + b_cost * P[t]
        + h_cost * H[t] * mwth_to_gj
        + c_cost * u[t]
        for t in range(T)
    )

    # 启停成本
    startup_cost = gp.quicksum(C_start * v[t] + C_shut * w[t] for t in range(T))

    # 碳排放成本
    #    实际碳排放：电侧 mu_e·P + 热侧 mu_h·H·3.6（MWth→GJ换算）
    #    免费配额：  电侧 eta_e·P + 热侧 eta_h·H·3.6
    #    净碳成本：  carbon_price × (实际排放 - 免费配额)
    carbon_cost = gp.quicksum(
        carbon_price * (
            (mu_e - eta_e) * P[t]
            + (mu_h - eta_h) * H[t] * mwth_to_gj
        )
        for t in range(T)
    )

    m.setObjective(revenue_e + revenue_h - fuel_cost - startup_cost - carbon_cost, GRB.MAXIMIZE)

    # ============================================================
    # 7: 求解
    # ============================================================
    m.optimize()

    # ============================================================
    # 8: 结果输出与分析
    # ============================================================
    if m.status in [GRB.OPTIMAL, GRB.SUBOPTIMAL]:
        status_tag = "最优解" if m.status == GRB.OPTIMAL else "次优解（时间截止）"
        hourly_results = []
        print("=" * 95)
        print(f"  300MW CHP 机组日前调度优化结果 [{status_tag}]")
        print("=" * 95)
       
        header = (f"{'时刻':<6}|{'电价':>8}|{'热需求':>8}|{'热出力':>8}"
                  f"|{'电出力':>8}|{'电收益':>9}|{'热收益':>9}|{'碳成本':>9}|{'时段净利':>10}|{'状态'}")
        print(header)
        print("-" * 95)

     
        total_rev_e, total_rev_h, total_fuel, total_su, total_co2 = (
            0.0, 0.0, 0.0, 0.0, 0.0
        )

        for t in range(T):
            pt  = P[t].X
            ht  = H[t].X
            ut  = u[t].X
            vt  = v[t].X
            wt  = w[t].X
            pr  = lambda_e[t]

            h_rev_e = pt * pr
            h_rev_h = ht * lambda_h * mwth_to_gj          

            h_fuel  = (
                a_cost * pt**2
                + b_cost * pt
                + h_cost * ht * mwth_to_gj
                + c_cost * ut
            )
            h_su    = C_start * vt + C_shut * wt
            h_co2   = carbon_price * (
                          (mu_e - eta_e) * pt
                        + (mu_h - eta_h) * ht * mwth_to_gj
                      )
           
            h_net   = h_rev_e + h_rev_h - h_fuel - h_su - h_co2

            total_rev_e += h_rev_e
            total_rev_h += h_rev_h         
            total_fuel  += h_fuel
            total_su    += h_su
            total_co2   += h_co2

            if vt > 0.5:
                flag = "▲ 启动"
            elif wt > 0.5:
                flag = "▼ 停机"
            elif ut > 0.5:
                flag = "  运行"
            else:
                flag = "  停机"

            print(f" {t:02d}:00 |{pr:>8.1f}|{H_demand[t]:>8.1f}|{ht:>8.1f}"
                  f"|{pt:>8.1f}|{h_rev_e:>9.2f}|{h_rev_h:>9.2f}"
                  f"|{h_co2:>9.2f}|{h_net:>10.2f}|{flag}")
            hourly_results.append({
                "hour": t,
                "power_price_yuan_per_mwh": pr,
                "heat_demand_mwth": H_demand[t],
                "heat_output_mwth": ht,
                "power_output_mw": pt,
                "unit_on": int(round(ut)),
                "startup": int(round(vt)),
                "shutdown": int(round(wt)),
                "electric_revenue_yuan": h_rev_e,
                "heat_revenue_yuan": h_rev_h,
                "fuel_cost_yuan": h_fuel,
                "startup_shutdown_cost_yuan": h_su,
                "carbon_cost_yuan": h_co2,
                "net_profit_yuan": h_net,
            })

        net_profit = total_rev_e + total_rev_h - total_fuel - total_su - total_co2
        max_heat_shortage = max(
            max(0.0, H_demand[t] - hourly_results[t]["heat_output_mwth"])
            for t in range(T)
        )
        max_heat_over_supply = max(
            max(0.0, hourly_results[t]["heat_output_mwth"] - H_demand[t])
            for t in range(T)
        )
        objective_gap = abs(net_profit - m.ObjVal)
        verification = {
            "status": status_tag,
            "status_code": int(m.status),
            "objective_value_yuan": m.ObjVal,
            "net_profit_yuan": net_profit,
            "objective_recalculation_gap_yuan": objective_gap,
            "max_heat_shortage_mwth": max_heat_shortage,
            "max_heat_over_supply_mwth": max_heat_over_supply,
            "strict_heat": strict_heat,
            "allow_heat_over_supply": allow_heat_over_supply,
            "is_objective_consistent": objective_gap < 1.0,
            "is_heat_balance_valid": max_heat_shortage < 1e-5
            and (allow_heat_over_supply or max_heat_over_supply < 1e-5),
        }
        totals = {
            "electric_revenue_yuan": total_rev_e,
            "heat_revenue_yuan": total_rev_h,
            "fuel_cost_yuan": total_fuel,
            "startup_shutdown_cost_yuan": total_su,
            "carbon_cost_yuan": total_co2,
            "net_profit_yuan": net_profit,
        }

        print("=" * 95)
        print(f"  求解器目标值    : {m.ObjVal:>15,.2f} 元")
        print(f"  全天电能收入    : {total_rev_e:>15,.2f} 元")
        print(f"  全天供热收入    : {total_rev_h:>15,.2f} 元")   
        print(f"  全天燃料成本    : {total_fuel:>15,.2f} 元")
        print(f"  全天启停成本    : {total_su:>15,.2f} 元")
        print(f"  全天碳排成本    : {total_co2:>15,.2f} 元")
        print(f"  ─────────────────────────────────────────")
        # 容差判断，避免浮点误差引起误报
        is_consistent = verification["is_objective_consistent"]
        tag = "（与求解器一致）" if is_consistent else " 仍有差异，请检查！"
        print(f"  全天净利润      : {net_profit:>15,.2f} 元  {tag}")
        print(f"  最大供热缺口    : {max_heat_shortage:>15,.6f} MWth")
        print(f"  最大供热超供    : {max_heat_over_supply:>15,.6f} MWth")
        print("=" * 95)
        if export_dir:
            export_path = Path(export_dir)
            export_path.mkdir(parents=True, exist_ok=True)
            csv_path = export_path / "revenue_model_hourly_results.csv"
            json_path = export_path / "revenue_model_validation.json"
            with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=list(hourly_results[0].keys()))
                writer.writeheader()
                writer.writerows(hourly_results)
            with json_path.open("w", encoding="utf-8") as f:
                json.dump(
                    {
                        "verification": verification,
                        "totals": totals,
                        "unit_params": unit_params,
                        "cost_params": cost_params,
                        "carbon_params": carbon_params,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            print(f"  验证JSON已导出 : {json_path}")
            print(f"  逐时结果CSV已导出: {csv_path}")

        figure_path = None
        if plot:
            if export_dir:
                figure_path = Path(export_dir) / "revenue_model_feasible_region.png"
            plot_feasible_region(
                m,
                P,
                H,
                u,
                unit_params,
                output_path=figure_path,
                show=export_dir is None,
            )
            if figure_path:
                print(f"  可行域图已导出 : {figure_path}")

        return {
            "hourly_results": hourly_results,
            "totals": totals,
            "verification": verification,
        }

    raise RuntimeError(f"Gurobi求解失败，状态码: {m.status}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CHP revenue model validation runner")
    parser.add_argument("--export-dir", default="validation_outputs", help="导出CSV/JSON/图片的目录")
    parser.add_argument("--no-plot", action="store_true", help="不生成可行域图")
    parser.add_argument("--relaxed-heat", action="store_true", help="演示模式：允许停机时不满足热负荷")
    parser.add_argument("--allow-heat-over-supply", action="store_true", help="允许供热超过需求")
    args = parser.parse_args()
    run_chp_optimization(
        plot=not args.no_plot,
        export_dir=args.export_dir,
        strict_heat=not args.relaxed_heat,
        allow_heat_over_supply=args.allow_heat_over_supply,
    )
