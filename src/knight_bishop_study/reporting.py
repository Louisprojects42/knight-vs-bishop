"""Render the expanded study from compact JSON/CSV; no PGNs required."""
import base64
import csv
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from . import sampling as study

import re


def main(out=Path('results')):
    OUT=Path(out)
    data=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    manifest=json.loads((OUT/'sampling_manifest.json').read_text(encoding='utf-8'))
    meta=data['metadata']
    colors={'knight':'#7158bf','bishop':'#168b83'}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                         'text.color':'#233249','axes.labelcolor':'#35445b','axes.edgecolor':'#bac5d0',
                         'xtick.color':'#526078','ytick.color':'#526078','savefig.facecolor':'white'})


    def lookup(cohort,speed='all',band='all',length='all'):
        return next((r for r in data[cohort] if (r['speed'],r['rating_band'],r['game_length'])==(speed,band,length)),None)


    def label_bands(ax):
        ax.set_xticks(range(6),[b.replace('-','–') for b in study.BANDS],rotation=35,ha='right')
        ax.grid(axis='y',alpha=.16)


    fig,axes=plt.subplots(2,2,figsize=(12,9))
    for ax,length in zip(axes.flat,study.LENGTHS):
        values=[lookup('captures',band=b,length=length) for b in study.BANDS]
        count=lookup('captures',length=length)['games'] if lookup('captures',length=length) else 0
        for piece in ('knight','bishop'):
            ax.plot(range(6),[r['capture_'+piece] if r else np.nan for r in values],'-o',color=colors[piece],lw=2,label=piece.title())
        ax.set_title(f'{length} · {count:,} sampled games',fontweight='bold')
        ax.set_ylabel('Captured points / player-game\n(two original pieces)')
        ax.set_ylim(bottom=0);label_bands(ax)
    axes[0,0].legend(frameon=False)
    fig.suptitle('Material captured by rating and actual game length',fontsize=17,fontweight='bold',y=.985)
    fig.text(.5,.935,'Stable-hash general cohort; pooled time controls. Move count is ceil(half-moves / 2).',ha='center',color='#64748b')
    fig.tight_layout(rect=[0,.025,1,.92]);fig.savefig(OUT/'captures_by_length.png',dpi=160);plt.close(fig)

    fig,axes=plt.subplots(2,2,figsize=(12,9))
    for ax,pool in zip(axes.flat,('all','bullet','blitz','rapid')):
        values=[lookup('evaluations',speed=pool,band=b) for b in study.BANDS]
        for piece in ('knight','bishop'):
            ax.plot(range(6),[r['loss_per_move_pp_'+piece] if r else np.nan for r in values],'-o',color=colors[piece],lw=2,label=piece.title())
        ax.set_title('All time controls (pooled)' if pool=='all' else pool.title(),fontweight='bold')
        ax.set_ylabel('Winning chance lost / evaluated move\n(percentage points; lower is better)')
        ax.set_ylim(bottom=0);label_bands(ax)
    axes[0,0].legend(frameon=False)
    fig.suptitle('Winning chance preserved on knight and bishop moves',fontsize=17,fontweight='bold',y=.985)
    fig.text(.5,.935,'Engine-annotated cohort only; immediate pre/post evaluations. This measures execution, not causal piece value.',ha='center',color='#64748b',fontsize=9)
    fig.tight_layout(rect=[0,.025,1,.92]);fig.savefig(OUT/'winning_chance_by_rating.png',dpi=160);plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(13,5.5))
    values=[lookup('outcomes',band=b) for b in study.BANDS]
    positions=np.arange(6)
    for offset,piece in ((-.18,'knight'),(.18,'bishop')):
        axes[0].bar(positions+offset,[r[piece+'_win_pct'] if r else np.nan for r in values],width=.34,color=colors[piece],label=piece.title())
    axes[0].set_title('Actual wins in matched positions',fontweight='bold')
    axes[0].set_ylabel('Observed win rate (%) · draws retained')
    axes[0].set_ylim(0,65);axes[0].legend(frameon=False);label_bands(axes[0])
    axes[1].axhline(0,color='#94a3b8',lw=1)
    for i,r in enumerate(values):
        if r:
            e=r['adjusted_difference_pp']
            axes[1].errorbar(i,e,yerr=[[e-r['adjusted_ci_low']],[r['adjusted_ci_high']-e]],fmt='o',capsize=4,
                             color='#168b83' if r['matched_games']>=200 else '#94a3b8')
    axes[1].set_title('Adjusted bishop minus knight',fontweight='bold')
    axes[1].set_ylabel('Win-probability difference (percentage points)')
    label_bands(axes[1])
    for ax in axes:
        ax.set_xticks(range(6),[b.replace('-','–')+f"\n(n={(r or {}).get('matched_games',0):,})" for b,r in zip(study.BANDS,values)],rotation=30,ha='right')
    fig.suptitle('Actual outcomes: balanced bishop versus knight positions',fontsize=17,fontweight='bold',y=.985)
    fig.text(.5,.89,f"{meta['matched_outcome_games']:,} qualifying games · equal material · same rating band · rating gap ≤100",ha='center',color='#64748b')
    fig.text(.5,.025,'Adjusted observational association; 95% window-clustered intervals. Earlier trades and unmeasured position details can confound results.',ha='center',fontsize=9,color='#64748b')
    fig.tight_layout(rect=[0,.07,1,.87]);fig.savefig(OUT/'actual_outcomes.png',dpi=180);plt.close(fig)

    with (OUT/'clock_normalization.csv').open(encoding='utf-8') as clock_file:
        clock=list(csv.DictReader(clock_file))
    fig,axes=plt.subplots(3,2,figsize=(13,12),sharey=True)
    tier_colors=plt.cm.viridis(np.linspace(.05,.9,6))
    for row,(tc,maximum) in enumerate((('180+0',180),('300+0',300),('600+0',600))):
        for col,piece in enumerate(('knight','bishop')):
            ax=axes[row,col]
            for band,color in zip(study.BANDS,tier_colors):
                cells=sorted([r for r in clock if r['time_control']==tc and r['piece']==piece and r['rating_band']==band
                              and int(r['eligible_moves'])>=50 and float(r['clock_bucket_start'])<=maximum],
                             key=lambda r:float(r['clock_bucket_start']))
                ax.plot([float(r['clock_bucket_start'])+2.5 for r in cells],
                        [float(r['normalized_blunder_200cp'])*100 for r in cells],lw=1.5,color=color,label=band)
            ax.set_title(f'{maximum//60}+0 minutes · {piece.title()}',fontweight='bold')
            ax.set_xlim(0,maximum);ax.set_ylim(bottom=0)
            ax.set_xlabel('MOVER clock after the move (seconds remaining)')
            if col==0:
                ax.set_ylabel('200cp event rate per eligible move (%)')
            ax.grid(alpha=.16)
    axes[0,0].legend(frameon=False,ncol=2,fontsize=8)
    fig.suptitle('Study-style normalized move events by clock and rating',fontsize=17,fontweight='bold',y=.99)
    fig.text(.5,.952,'Events / all eligible piece-move opportunities; 5-second buckets with at least 50 moves. Engine and clock cohort.',ha='center',fontsize=9,color='#64748b')
    fig.text(.5,.02,'200cp loss excluding positions staying ≥+300cp. This is an explicitly defined event, not a claim about the current Lichess blunder classifier.',ha='center',fontsize=9,color='#64748b')
    fig.tight_layout(rect=[0,.04,1,.94]);fig.savefig(OUT/'clock_event_rates.png',dpi=150);plt.close(fig)

    fig,axes=plt.subplots(2,2,figsize=(12,9))
    for ax,length in zip(axes.flat,study.LENGTHS):
        ax.axhline(0,color='#94a3b8',lw=1)
        rows=[lookup('outcomes',band=b,length=length) for b in study.BANDS]
        for i,r in enumerate(rows):
            if r and r['matched_games']>=200 and r['windows']>=6:
                value=r['raw_difference_pp']
                ax.errorbar(i,value,yerr=[[value-r['raw_ci_low']],[r['raw_ci_high']-value]],fmt='o',capsize=4,color='#168b83')
        pooled=lookup('outcomes',length=length)
        ax.set_title(f"{length} · {pooled['matched_games']:,} games" if pooled else length,fontweight='bold')
        if pooled is None:
            ax.text(.5,.5,'No qualifying positions\nCheckpoints start after move 20',transform=ax.transAxes,ha='center',va='center',color='#64748b')
        ax.set_ylabel('Observed bishop minus knight win rate (pp)')
        label_bands(ax)
        ax.set_xticks(range(6),[b.replace('-','–')+f"\n(n={r['matched_games']:,})" if r else b.replace('-','–')+'\n(n=0)' for b,r in zip(study.BANDS,rows)],rotation=30,ha='right')
    fig.suptitle('Actual win-rate differences by eventual game length',fontsize=17,fontweight='bold',y=.985)
    fig.text(.5,.935,'Unadjusted observed differences; draws retained; pointwise 95% window-bootstrap intervals.',ha='center',fontsize=9,color='#64748b')
    fig.text(.5,.015,'Cells below 200 games or 6 windows omitted. Eventual-length stratification is descriptive and can introduce selection bias.',ha='center',fontsize=9,color='#64748b')
    fig.tight_layout(rect=[0,.04,1,.92]);fig.savefig(OUT/'outcomes_by_length.png',dpi=160);plt.close(fig)

    overall={k:lookup(k) for k in ('captures','evaluations','outcomes')}
    verdict={'bishop':'The model shows an overall bishop association with winning.',
             'knight':'The model shows an overall knight association with winning.',
             'inconclusive':'Actual outcomes do not establish an overall winner.',
             'too_few_games':'The outcome cohort is too small to establish an overall winner.'}[overall['outcomes']['adjusted_leader']]
    def number(value,digits=2):
        return '—' if value is None else f'{value:.{digits}f}'

    def value(row,key):
        return (row or {}).get(key)

    notes=['# Knight vs bishop: six-month results','',
           f"Source coverage: April–September 2026, {meta['windows']} random distributed windows, {len(meta['sampled_dates'])} observed dates.",
           f"Scanned {manifest['scanned_counts']['records_seen']:,} records; general capture cohort {meta['general_games']:,} games; evaluated cohort {meta['annotated_games']:,} games / {meta['evaluated_minor_moves']:,} eligible minor-piece moves; actual-outcome cohort {meta['matched_outcome_games']:,} balanced games.",'',
           '**Main finding:** '+verdict+' The capture, influence and engine metrics describe different aspects of contribution.', '',
           '| Metric | Knights | Bishops |','|---|---:|---:|',
           f"| Captured points / player-game (both original pieces) | {overall['captures']['capture_knight']:.3f} | {overall['captures']['capture_bishop']:.3f} |",
           f"| Attacked squares / original piece / position | {overall['captures']['influence_knight']:.3f} | {overall['captures']['influence_bishop']:.3f} |",
           f"| Legal destinations / original piece / owner turn | {overall['captures']['mobility_knight']:.3f} | {overall['captures']['mobility_bishop']:.3f} |",
           f"| Engine winning chance LOST / evaluated move (pp; lower better) | {overall['evaluations']['loss_per_move_pp_knight']:.3f} | {overall['evaluations']['loss_per_move_pp_bishop']:.3f} |",
           f"| Signed winning-chance change / evaluated move (pp) | {overall['evaluations']['delta_per_move_pp_knight']:.3f} | {overall['evaluations']['delta_per_move_pp_bishop']:.3f} |",
           f"| Cumulative signed change / original piece / qualified player-game (pp) | {overall['evaluations']['delta_per_piece_game_pp_knight']:.3f} | {overall['evaluations']['delta_per_piece_game_pp_bishop']:.3f} |",
           f"| Actual win rate in balanced B-v-N positions (%) | {overall['outcomes']['knight_win_pct']:.2f} | {overall['outcomes']['bishop_win_pct']:.2f} |",
           f"| Adjusted actual win probability (%) | {overall['outcomes']['adjusted_knight_win_pct']:.2f} | {overall['outcomes']['adjusted_bishop_win_pct']:.2f} |",'',
           f"Adjusted bishop-minus-knight difference: **{overall['outcomes']['adjusted_difference_pp']:+.2f} percentage points**, 95% interval [{overall['outcomes']['adjusted_ci_low']:+.2f}, {overall['outcomes']['adjusted_ci_high']:+.2f}]. Shared observed draw rate: {overall['outcomes']['draw_pct']:.2f}%.",'',
           '| Rating band | General games | Captures N / B | Engine loss N / B (pp/move) | Matched outcome games | Adjusted B−N win probability (pp), 95% interval |',
           '|---|---:|---:|---:|---:|---:|']
    for band in study.BANDS:
        c,e,o=[lookup(k,band=band) for k in ('captures','evaluations','outcomes')]
        notes.append(f"| {band} | {(c or {}).get('games',0):,} | {number(value(c,'capture_knight'))} / {number(value(c,'capture_bishop'))} | {number(value(e,'loss_per_move_pp_knight'))} / {number(value(e,'loss_per_move_pp_bishop'))} | {(o or {}).get('matched_games',0):,} | {number(value(o,'adjusted_difference_pp'))} [{number(value(o,'adjusted_ci_low'))}, {number(value(o,'adjusted_ci_high'))}] |")
    notes += ['', 'The HTML table also separates time controls and completed move counts. All rating bands are lower-inclusive and upper-exclusive.', '',
              '**Interpretation:** the actual-outcome comparison is an adjusted observational association in a defined equal-material bishop-versus-knight population. It does not identify causal credit for every original piece throughout the game. Engine losses measure execution on evaluated moves; they do not include all passive threats or opponent-induced errors.', '',
              f"Validation: held-out window Brier score {data['model_validation']['brier_score']:.4f}, baseline {data['model_validation']['baseline_brier']:.4f}; log loss {data['model_validation']['log_loss']:.4f}, baseline {data['model_validation']['baseline_log_loss']:.4f}.", '',
              f"Downloaded {meta['total_range_download_gb']:.2f} GB in two RAM-only passes over {meta['source_archive_gb']:.1f} GB of source archives. These are sampled windows, not a full-archive census. Raw archive windows are not retained. Reduced data, manifests, model, numerator/normalizer tables and methods are saved.", '',
              'Methods: [METHODS.md](../docs/METHODS.md). Sources: [Lichess database](https://database.lichess.org/), [winning-chance formula](https://lichess.org/page/accuracy), [reference study](https://github.com/Antiochian/chess-blunders/blob/main/README.md).']
    (OUT/'report.md').write_text('\n'.join(notes)+'\n',encoding='utf-8')

    def image(name):
        return 'data:image/png;base64,'+base64.b64encode((OUT/name).read_bytes()).decode()

    cards=f'''<article><h3>General capture cohort</h3><strong>{meta['general_games']:,}</strong><p>games selected by stable hash</p></article>
    <article><h3>Evaluated move cohort</h3><strong>{meta['evaluated_minor_moves']:,}</strong><p>eligible knight/bishop moves in {meta['annotated_games']:,} games</p></article>
    <article><h3>Actual outcomes</h3><strong>{meta['matched_outcome_games']:,}</strong><p>balanced bishop-versus-knight games</p></article>'''
    e=overall['evaluations'];o=overall['outcomes'];c=overall['captures']
    overview=f'''<p><strong>{verdict}</strong> The metrics describe different aspects of contribution.</p><p>Captured material per player-game: <span class="n">knights {c['capture_knight']:.2f}</span> / <span class="b">bishops {c['capture_bishop']:.2f}</span> pawn-equivalent points from each pair of original pieces.</p>
    <p>Geometric influence: <span class="n">knights {c['influence_knight']:.2f}</span> / <span class="b">bishops {c['influence_bishop']:.2f}</span> attacked squares per original piece per position. Legal mobility: knights {c['mobility_knight']:.2f} / bishops {c['mobility_bishop']:.2f} destinations per original piece on its owner's turn. Captured pieces contribute zero thereafter; overlapping attacks count per piece.</p>
    <p>Engine winning chance lost per evaluated move: <span class="n">knights {e['loss_per_move_pp_knight']:.2f}</span> / <span class="b">bishops {e['loss_per_move_pp_bishop']:.2f}</span> percentage points; lower is better.</p>
    <p>Cumulative signed engine change per original piece per qualified player-game: knights {e['delta_per_piece_game_pp_knight']:.2f} / bishops {e['delta_per_piece_game_pp_bishop']:.2f} percentage points, in {e['qualified_player_games']:,} player-games with at least 80% adjacent-evaluation coverage. This sums changes after that piece's own moves; negative values record lost chances, and move frequency affects the total.</p>
    <p>Adjusted bishop-minus-knight actual win probability: <strong>{o['adjusted_difference_pp']:+.2f} percentage points</strong>, 95% interval [{o['adjusted_ci_low']:+.2f}, {o['adjusted_ci_high']:+.2f}]. Raw win rates: knights {o['knight_win_pct']:.2f}%, bishops {o['bishop_win_pct']:.2f}%, draws {o['draw_pct']:.2f}%.</p>'''
    source_description=f"{manifest['scanned_counts']['records_seen']:,} records scanned across April–September 2026, {meta['windows']} distributed random-byte windows and {meta['sampled_date_count']} observed dates. Both players rated at least 500."
    payload=json.dumps(data,separators=(',',':')).replace('<','\\u003c')
    template='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Knight vs bishop · Expanded study</title>
    <style>:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#233249;background:#f3f6fa}*{box-sizing:border-box}body{margin:0}main{max-width:1400px;margin:auto;padding:38px 28px 70px}h1{font-size:38px;letter-spacing:-1px;margin:10px 0}h2{margin-top:38px;font-size:24px}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:2px;color:#64748b;font-weight:700}p,li{line-height:1.65}.lead{font-size:18px;max-width:1100px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:25px}.cards article,.box{background:white;border:1px solid #e0e6ef;border-radius:12px;padding:20px}.cards h3{font-size:15px;margin:0}.cards strong{display:block;font-size:33px;margin-top:10px}.cards p{font-size:13px;color:#64748b}.notice{background:#fff8e7;border-left:4px solid #d4a94a;padding:15px 20px;margin:22px 0}.n{color:#7158bf}.b{color:#168b83}.quiet{color:#64748b;font-size:13px}.controls{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:18px 0}select{background:white;border:1px solid #bac5d0;border-radius:6px;padding:9px 12px;font:inherit}.table-wrap{overflow:auto;background:white;border:1px solid #e0e6ef;border-radius:10px}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}th,td{text-align:right;padding:12px 13px;border-bottom:1px solid #edf0f5}th{background:#eaf0f7;font-size:12px}th:first-child,td:first-child{text-align:left}td small{display:block;font-size:11px;color:#64748b;margin-top:4px}.total{background:#f6f8fc;font-weight:600}.sparse{color:#8893a5}.chart{background:white;border:1px solid #e0e6ef;padding:12px;border-radius:12px;margin:25px 0}.chart img{width:100%;height:auto;display:block}details{background:white;border:1px solid #e0e6ef;padding:17px 22px;border-radius:10px;margin-top:16px}summary{font-weight:600;cursor:pointer}a{color:#2569aa}.footer{margin-top:35px;font-size:13px;color:#64748b}@media(max-width:850px){main{padding:22px 15px}h1{font-size:29px}.cards{grid-template-columns:1fr}.cards strong{font-size:29px}}
    </style></head><body><main><div class="eyebrow">Six months · reduced-data study · real outcomes and engine changes</div><h1>Knight versus bishop: evidence on winning</h1><p class="lead">__SOURCE__</p><div class="cards">__CARDS__</div>
    <div class="notice"><strong>Three different populations.</strong> Captures use the general hash sample, engine rates use evaluated moves, and actual outcomes use all qualifying equal-material bishop-versus-knight positions found in the windows. Sample sizes must not be added together. The source archives were sampled, not exhaustively scanned.</div>
    <h2>Overall findings</h2><div class="box">__OVERVIEW__<p class="quiet">Actual outcomes are an adjusted observational association. Engine losses measure move execution. Neither assigns complete causal credit to a piece.</p></div>
    <h2>Rating, time-control and game-length comparisons</h2><div class="controls"><label>Time control <select id="speed"><option value="all">All controls (pooled)</option><option value="ultrabullet">Ultrabullet</option><option value="bullet">Bullet</option><option value="blitz">Blitz</option><option value="rapid">Rapid</option><option value="classical">Classical</option><option value="unknown_or_correspondence">Unknown / correspondence</option></select></label><label>Completed move count <select id="length"><option value="all">All game lengths</option><option>1-20 moves</option><option>21-40 moves</option><option>41-60 moves</option><option>61+ moves</option></select></label></div>
    <div class="table-wrap"><table><thead><tr><th>Owner rating</th><th>General<br>games</th><th>Captured points<br>Knights / Bishops</th><th>Influence / mobility<br>Knights / Bishops</th><th>Engine chance LOST / move (pp)<br>Knights / Bishops</th><th>Matched actual wins (%)<br>Knights / Bishops</th><th>Adjusted B−N win probability<br>pp and 95% interval</th></tr></thead><tbody id="rows"></tbody></table></div><p class="quiet">Lower bounds are inclusive and upper bounds exclusive: exactly 750 belongs to 750–1000. Captures are the pair's combined points per player-game. All loss/opportunity denominators, game counts and matched counts are retained. Sparse cells remain inconclusive; missing cells display —. Short games cannot qualify for the outcome checkpoints.</p>
    <div class="chart"><img src="__ACTUAL__" alt="Observed win rates and adjusted bishop minus knight win probabilities by rating"></div><div class="chart"><img src="__ENGINE__" alt="Engine winning-chance loss by rating for bullet blitz and rapid"></div><div class="chart"><img src="__CAPTURE__" alt="Knight and bishop captures in four completed move-count groups"></div><div class="chart"><img src="__LENGTH__" alt="Observed bishop minus knight win rates by completed game length, with intervals and counts"></div>
    <h2>Record and normalize like the reference study</h2><p>The preprocessing keeps immediate before/after evaluations, mover clock, owning-player rating, piece identity and valid opportunity counts. Rates divide event counts by <em>all eligible piece moves in that bucket</em>. The reduced SQLite databases and CSV normalizers allow new plots without downloading PGNs again.</p><div class="chart"><img src="__CLOCK__" alt="Study-style 200 centipawn event rates against remaining clock for 3 5 and 10 minute games"></div>
    <details open><summary>What “winning contribution” measures here</summary><p>Actual outcome comparison: each side has one original minor piece, bishop versus knight, and equal pawn/rook/queen counts. Both owners are in the same rating band and within 100 rating points. Select the first qualifying predeclared checkpoint after move 20 with at least two more full moves to follow.</p><p>Adjusted win probabilities use a regression of real wins against piece type, rating gap, colour, move number, material, pawn/king features, time-control pool and month. Holding those model features fixed provides a relative bishop-vs-knight contrast. Earlier trades, piece-square placement, unmeasured position details and player choices can still confound it.</p><p>Engine comparison: convert centipawns using the Lichess formula, compare immediately adjacent positions in the mover's perspective and record signed change and chance lost. A best move often maintains a chance already present. These move statistics do not capture all passive support or threats inducing an opponent's mistake.</p></details>
    <details><summary>Coverage, uncertainty and validation</summary><p>__SAMPLING__</p><p>Pointwise 95% capture and move-rate intervals use 1,000 archive-window bootstrap replicates. The actual-outcome model uses covariance clustered by window. No adjustment for multiple subgroup comparisons; repeated players across windows and selection into engine analysis remain limitations.</p><p>__VALIDATION__</p><p>Completed move count is not an outcome-model predictor. Splitting results by eventual length is descriptive and can introduce selection bias. Lichess ratings belong to separate time-control pools; pooled rows reflect the sampled mixture.</p></details>
    <details><summary>Saved analysis and data</summary><ul><li><a href="../docs/METHODS.md">Methods and reproduction instructions</a></li><li><a href="captures_by_rating_speed_length.csv">Capture summaries</a> · <a href="winning_chance_by_rating_speed_length.csv">Engine winning-chance summaries</a> · <a href="actual_outcomes_by_rating_speed_length.csv">Actual-outcome summaries</a></li><li><a href="clock_normalization.csv">Clock numerator/denominator records</a> · <a href="matched_positions.csv">Matched positions and FENs</a></li><li><a href="study.sqlite">Reduced game and move database</a> · <a href="outcomes.sqlite">Reduced outcome database</a></li><li><a href="sampling_manifest.json">Sampling and filtering manifest</a> · <a href="outcome_model.json">Model, validation and coefficients</a></li></ul></details>
    <p class="footer">Sources: <a href="https://database.lichess.org/">Lichess open database</a> · <a href="https://lichess.org/page/accuracy">Lichess winning-chance formula</a> · <a href="https://github.com/Antiochian/chess-blunders/blob/main/README.md">Antiochian/chess-blunders</a>. The report works offline and embeds all plots.</p></main><script>
    const data=__PAYLOAD__;
    const bands=['all','500-750','750-1000','1000-1500','1500-2000','2000-2500','2500+'];
    const speed=document.getElementById('speed'),length=document.getElementById('length');
    function find(kind,b){return data[kind].find(r=>r.speed===speed.value&&r.rating_band===b&&r.game_length===length.value)}
    function f(n,d=2){return n===null||n===undefined?'—':n.toFixed(d)}
    function count(n){return n===undefined?'—':n.toLocaleString()}
    function render(){document.getElementById('rows').innerHTML=bands.map(b=>{const c=find('captures',b),e=find('evaluations',b),o=find('outcomes',b);const status=o?o.adjusted_leader==='too_few_games'?'Sparse cell':o.adjusted_leader==='inconclusive'?'Inconclusive':o.adjusted_leader==='bishop'?'Bishop association':'Knight association':'No qualifying positions';return `<tr class="${b==='all'?'total':''}"><td>${b==='all'?'Overall':b}</td><td>${count(c?.games)}<small>${count(c?.player_games)} player-games</small></td><td><span class="n">${f(c?.capture_knight)}</span> / <span class="b">${f(c?.capture_bishop)}</span><small>B−N ${f(c?.capture_difference)} [${f(c?.capture_ci_low)}, ${f(c?.capture_ci_high)}]</small></td><td><span class="n">${f(c?.influence_knight)}</span> / <span class="b">${f(c?.influence_bishop)}</span><small>Legal mobility ${f(c?.mobility_knight)} / ${f(c?.mobility_bishop)}</small></td><td><span class="n">${f(e?.loss_per_move_pp_knight)}</span> / <span class="b">${f(e?.loss_per_move_pp_bishop)}</span><small>${count(e?.knight_eligible_moves)} / ${count(e?.bishop_eligible_moves)} eligible moves</small></td><td><span class="n">${f(o?.knight_win_pct)}</span> / <span class="b">${f(o?.bishop_win_pct)}</span><small>${count(o?.matched_games)} games · draws ${f(o?.draw_pct)}%</small><small>Raw B−N ${f(o?.raw_difference_pp)} [${f(o?.raw_ci_low)}, ${f(o?.raw_ci_high)}]</small></td><td class="${o?.adjusted_leader==='too_few_games'?'sparse':''}">${f(o?.adjusted_difference_pp)} [${f(o?.adjusted_ci_low)}, ${f(o?.adjusted_ci_high)}]<small>${status}</small></td></tr>`}).join('')}
    speed.addEventListener('change',render);length.addEventListener('change',render);render();
    </script></body></html>'''
    validation=data['model_validation']
    substitutions={'__SOURCE__':html.escape(source_description),'__CARDS__':cards,'__OVERVIEW__':overview,
                   '__ACTUAL__':image('actual_outcomes.png'),'__ENGINE__':image('winning_chance_by_rating.png'),
                   '__CAPTURE__':image('captures_by_length.png'),'__LENGTH__':image('outcomes_by_length.png'),
                   '__CLOCK__':image('clock_event_rates.png'),'__PAYLOAD__':payload,
                   '__SAMPLING__':f"The sampled source windows contain {manifest['scanned_counts']['records_seen']:,} records and span {meta['sampled_date_count']} observed dates. Total two-pass range transfers: {meta['total_range_download_gb']:.2f} GB across archives totalling {meta['source_archive_gb']:.1f} GB. Random byte windows and complete-frame recovery are not an exact uniform sample of games. Raw archive payloads are kept only in RAM and released after processing.",
                   '__VALIDATION__':f"Outcome validation held out {validation['held_out_games']:,} games from {len(validation['held_out_windows'])} whole windows. Brier score {validation['brier_score']:.4f} versus constant baseline {validation['baseline_brier']:.4f}; log loss {validation['log_loss']:.4f} versus {validation['baseline_log_loss']:.4f}. The improvement over baseline is modest. Calibration and convergence are recorded."}
    for key,value in substitutions.items():
        template=template.replace(key,value)
    # Optional reduced datasets are intentionally outside Git.
    for optional in ('study.sqlite','outcomes.sqlite','matched_positions.csv'):
        if not (OUT/optional).exists():
            template=re.sub(r'<a href="'+re.escape(optional)+r'">(.*?)</a>',r'<span>\1 (optional dataset)</span>',template)
    template=template.replace('<details><summary>Saved analysis and data</summary>', '<details><summary>Saved analysis and data</summary><p><a href="../docs/DATA.md">Reduced data and reproduction instructions</a></p>')
    (OUT/'report.html').write_text(template,encoding='utf-8')
    print('Created expanded report and five figures')


if __name__ == '__main__':
    main()
