"""Make shareable scientific figures and an offline graph gallery from retained results."""
import base64
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np

from datetime import datetime


def main(out=Path('results')):
    OUT=Path(out)
    data=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    manifest=json.loads((OUT/'sampling_manifest.json').read_text(encoding='utf-8'))
    meta=data['metadata']
    first,last=[datetime.strptime(m,'%Y-%m') for m in (meta['months'][0],meta['months'][-1])]
    period=(first.strftime('%B')+'–'+last.strftime('%B %Y')) if first.year==last.year else first.strftime('%B %Y')+'–'+last.strftime('%B %Y')
    bands=data['metadata']['rating_bands']
    lengths=data['metadata']['length_bands']
    labels=[b.replace('-','–') for b in bands]
    N,B='#7158bf','#168b83'
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,
                         'axes.spines.right':False,'text.color':'#233249','axes.labelcolor':'#35445b',
                         'xtick.color':'#526078','ytick.color':'#526078','axes.edgecolor':'#bac5d0'})


    def get(cohort,band='all',length='all'):
        return next((r for r in data[cohort] if (r['speed'],r['rating_band'],r['game_length'])==('all',band,length)),None)


    def rating_axis(ax):
        ax.set_xticks(range(6),labels,rotation=25,ha='right')
        ax.grid(axis='y',alpha=.15)
        ax.set_axisbelow(True)


    fig,axes=plt.subplots(2,2,figsize=(15,11))
    fig.suptitle('Knight vs bishop: what the games show',x=.07,ha='left',y=.97,fontsize=25,fontweight='bold')
    fig.text(.07,.92,f"{manifest['scanned_counts']['records_seen']/1e6:.2f} million records scanned · {meta['windows']} distributed samples · {period} · both players rated ≥500",fontsize=11,color='#64748b')
    fig.text(.07,.875,f"{meta['general_games']:,} capture games",fontsize=14,fontweight='bold')
    fig.text(.37,.875,f"{meta['evaluated_minor_moves']/1e6:.2f} million evaluated moves",fontsize=14,fontweight='bold')
    fig.text(.72,.875,f"{meta['matched_outcome_games']:,} outcome games",fontsize=14,fontweight='bold')
    x=np.arange(6)
    ax=axes[0,0]
    rows=[get('captures',b) for b in bands]
    for shift,piece,color in ((-.18,'knight',N),(.18,'bishop',B)):
        ax.bar(x+shift,[r['capture_'+piece] if r else np.nan for r in rows],width=.34,color=color,label=piece.title())
    ax.set_title('Material captured by original pieces',loc='left',fontweight='bold',pad=14)
    ax.set_ylabel('Pawn-equivalent points / player-game\n(combined pair of original pieces)')
    ax.set_ylim(0,5.3);ax.legend(frameon=False,ncol=2,loc='upper left');rating_axis(ax)
    ax=axes[0,1]
    for piece,color in (('knight',N),('bishop',B)):
        ax.plot(x,[r['influence_'+piece] if r else np.nan for r in rows],'-o',color=color,lw=2.5,label=piece.title())
    ax.set_title('Geometric influence by rating',loc='left',fontweight='bold',pad=14)
    ax.set_ylabel('Attacked squares / original piece / position\n(captured pieces contribute zero)')
    ax.set_ylim(0,5.3);ax.legend(frameon=False,ncol=2,loc='upper left');rating_axis(ax)
    ax=axes[1,0]
    rows=[get('evaluations',b) for b in bands]
    for piece,color in (('knight',N),('bishop',B)):
        ax.plot(x,[r['loss_per_move_pp_'+piece] if r else np.nan for r in rows],'-o',color=color,lw=2.5,label=piece.title())
    ax.set_title('Winning chance lost on moves',loc='left',fontweight='bold',pad=14)
    ax.set_ylabel('Winning chance lost / evaluated move (pp)\n(lower is better)')
    ax.set_ylim(0,7.4);ax.legend(frameon=False,ncol=2,loc='upper right');rating_axis(ax)
    ax=axes[1,1]
    rows=[get('outcomes')]+[get('outcomes',b) for b in bands]
    ax.axvline(0,color='#94a3b8',lw=1)
    for i,row in enumerate(rows):
        if row is None:
            continue
        value=row['adjusted_difference_pp']
        sparse=row['adjusted_leader']=='too_few_games'
        ax.errorbar(value,i,xerr=[[value-row['adjusted_ci_low']],[row['adjusted_ci_high']-value]],fmt='o',capsize=4,
                    color='#94a3b8' if sparse else ('#233249' if i==0 else B),markersize=7 if i==0 else 5,lw=1.5)
    ax.set_yticks(range(7),['Overall']+labels)
    ax.invert_yaxis();ax.grid(axis='x',alpha=.15)
    ax.set_title('Actual wins and adjusted uncertainty',loc='left',fontweight='bold',pad=14)
    ax.set_xlabel('Adjusted bishop minus knight win probability (pp)\n← knight association                      bishop association →')
    ax.text(.99,.03,f"500–750: {(get('outcomes',bands[0]) or {}).get('matched_games',0):,} outcome games",ha='right',transform=ax.transAxes,fontsize=9,color='#64748b')
    fig.text(.07,.025,f"Overall adjusted difference: {get('outcomes')['adjusted_difference_pp']:+.2f} pp (95% interval {get('outcomes')['adjusted_ci_low']:+.2f} to {get('outcomes')['adjusted_ci_high']:+.2f}). Observational evidence, not causal piece value.",fontsize=10,color='#64748b')
    fig.subplots_adjust(left=.08,right=.96,top=.815,bottom=.13,hspace=.57,wspace=.36)
    fig.savefig(OUT/'visual_summary.png',dpi=170,facecolor='white')
    fig.savefig(OUT/'visual_summary.svg',facecolor='white')
    plt.close(fig)

    cmap=LinearSegmentedColormap.from_list('pieces',[N,'#f4f7fa',B])
    fig,axes=plt.subplots(1,2,figsize=(15,7.3))
    for ax,cohort,metric,low,high,title,unit in (
        (axes[0],'captures','capture_difference','capture_ci_low','capture_ci_high','Material captured: bishop minus knight','Pawn-equivalent points / player-game'),
        (axes[1],'outcomes','raw_difference_pp','raw_ci_low','raw_ci_high','Actual win rate: bishop minus knight','Observed win-rate difference (pp)')):
        matrix=np.full((6,4),np.nan)
        for i,band in enumerate(bands):
            for j,length in enumerate(lengths):
                row=get(cohort,band,length)
                count=row.get('matched_games',row.get('games',0)) if row else 0
                if row and count>=200 and row['windows']>=6:
                    matrix[i,j]=row[metric]
        finite=matrix[np.isfinite(matrix)]
        limit=max(.01,float(np.max(np.abs(finite)))) if finite.size else 1.
        im=ax.imshow(np.ma.masked_invalid(matrix),cmap=cmap,norm=TwoSlopeNorm(vmin=-limit,vcenter=0,vmax=limit),aspect='auto')
        ax.set_facecolor('#e6eaf0')
        for i,band in enumerate(bands):
            for j,length in enumerate(lengths):
                row=get(cohort,band,length)
                count=row.get('matched_games',row.get('games',0)) if row else 0
                if np.isfinite(matrix[i,j]):
                    star=' *' if row[low]>0 or row[high]<0 else ''
                    color='white' if abs(matrix[i,j])>limit*.65 else '#233249'
                    text=f'{matrix[i,j]:+.2f}{star}\nn={count:,}'
                else:
                    color='#64748b'
                    text='No positions' if row is None else f'Sparse\nn={count:,}'
                ax.text(j,i,text,ha='center',va='center',fontsize=10,color=color)
        ax.set_xticks(range(4),[l.replace(' moves','')+'\nmoves' for l in lengths])
        ax.set_yticks(range(6),labels)
        ax.set_title(title,fontsize=14,fontweight='bold',pad=16)
        bar=fig.colorbar(im,ax=ax,orientation='horizontal',pad=.12,fraction=.045)
        bar.set_label(unit,fontsize=10)
    fig.suptitle('How the comparison changes with rating and game length',fontsize=21,fontweight='bold',y=.97)
    fig.text(.5,.905,'Purple favors knights · green favors bishops · grey cells lack enough qualifying games',ha='center',color='#64748b')
    fig.text(.5,.025,'* Pointwise 95% interval excludes zero; no correction for multiple comparisons. Eventual-length comparisons are descriptive.',ha='center',fontsize=10,color='#64748b')
    fig.subplots_adjust(left=.09,right=.96,top=.825,bottom=.16,wspace=.27)
    fig.savefig(OUT/'rating_length_heatmaps.png',dpi=170,facecolor='white')
    fig.savefig(OUT/'rating_length_heatmaps.svg',facecolor='white')
    plt.close(fig)

    charts=[('visual_summary.png','The main findings'),('rating_length_heatmaps.png','Rating and completed game length'),
            ('actual_outcomes.png','Actual wins and adjusted uncertainty'),('winning_chance_by_rating.png','Engine winning chances and time controls'),
            ('captures_by_length.png','Material captured by game length'),('outcomes_by_length.png','Actual outcomes within length groups'),
            ('clock_event_rates.png','Normalized clock and rating curves')]
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Knight vs bishop · Graph gallery</title>',
           '<style>body{margin:0;background:#f3f6fa;color:#233249;font:16px system-ui}main{max-width:1350px;margin:auto;padding:30px 20px}h1{font-size:32px}p{line-height:1.65}article{background:white;padding:20px;border-radius:12px;margin:25px 0}img{width:100%;height:auto}a{color:#2569aa}nav{display:flex;gap:15px;flex-wrap:wrap}h2{font-size:21px}</style><main>',
           '<h1>Knight vs bishop: the graphs</h1><p>Captures, spatial influence, engine changes, and actual outcomes measure different aspects of contribution. Read the full report for estimates and uncertainty.</p>',
           '<nav><a href="report.html">Full report and filters</a><a href="../docs/METHODS.md">Methods</a><a href="visual_summary.svg">Summary as SVG</a><a href="rating_length_heatmaps.svg">Heatmaps as SVG</a></nav>',
           f"<p>{meta['windows']} distributed source windows, {period}. Both owners rated at least 500. The 500–750 outcome cohort has {(get('outcomes',bands[0]) or {}).get('matched_games',0):,} games. Intervals are exploratory; these results do not identify causal piece value.</p>"]
    for name,title in charts:
        encoded=base64.b64encode((OUT/name).read_bytes()).decode()
        parts.append(f'<article><h2>{title}</h2><img src="data:image/png;base64,{encoded}" alt="{title}"><p><a href="{name}">Download PNG</a></p></article>')
    parts.append('</main></html>')
    (OUT/'graphs.html').write_text('\n'.join(parts),encoding='utf-8')
    (OUT/'index.html').write_text('\n'.join(parts),encoding='utf-8')
    report=OUT/'report.html'
    text=report.read_text(encoding='utf-8')
    marker='<h2>Overall findings</h2>'
    link='<p><a href="graphs.html">Open the graph gallery and download shareable figures</a></p>'
    if link not in text:
        assert marker in text
        report.write_text(text.replace(marker,link+marker),encoding='utf-8')
    print('Created visual summary, rating/length heatmaps, SVG exports, and offline graph gallery.')


if __name__ == '__main__':
    main()
