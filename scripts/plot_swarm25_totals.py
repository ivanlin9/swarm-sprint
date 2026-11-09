"""Offline ordinary-agent total and mean extraction across completed repetitions."""
from pathlib import Path
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from peer_silencing.storage import unseal

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/govsim/swarm25-replicates-v1'
OUT=ROOT/'reports/govsim-swarm25-replicates/final-line-graphs'
COUNTS=[0,1,3,5,8,10]

def main():
    totals=[]
    for block in [1,2,3]:
        values=[]
        for count in COUNTS:
            row=unseal(RUN/f'block-{block:02d}/r{count}/outcome.json')
            assert len(row['ordinary_allocated'])==15
            values.append(sum(row['ordinary_allocated']))
        totals.append(values)
    averages=[[v/15 for v in row] for row in totals]
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    for ax,data,title,ylabel in zip(axes,[totals,averages],
        ['Total tons fished by ordinary agents','Average tons fished per ordinary agent'],
        ['Total actual catch (tons; 15 ordinary agents)','Mean actual catch (tons per ordinary agent)']):
        for i,values in enumerate(data):
            ax.plot(COUNTS,values,'o--',linewidth=1.2,alpha=.55,label=f'Repetition {i+1}',markersize=4)
        means=[statistics.mean(row[j] for row in data) for j in range(6)]
        ax.plot(COUNTS,means,'o-',color='#152d45',linewidth=2.7,markersize=6,label='Mean of 3 repetitions',zorder=5)
        for x,y in zip(COUNTS,means):ax.annotate(f'{y:.1f}',(x,y),xytext=(0,9),textcoords='offset points',ha='center',fontsize=9,color='#152d45')
        ax.set_title(title);ax.set_xlabel('Number of recruiters (25-agent swarm)');ax.set_ylabel(ylabel)
        ax.set_xticks(COUNTS);ax.set_ylim(0,max(max(row) for row in data)*1.2)
        ax.grid(alpha=.2);ax.legend(fontsize=9,loc='upper left')
    fig.suptitle('Recruiter count and ordinary-agent extraction',fontsize=16,weight='bold')
    fig.text(.5,.025,'Actual allocations, not requests. Recruiter/source-slot catches excluded. Three matched repetitions; no significance claim.',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.065,1,.94))
    OUT.mkdir(parents=True,exist_ok=True)
    fig.savefig(OUT/'total_and_average_tons.png',dpi=200,facecolor='white')
    fig.savefig(OUT/'total_and_average_tons.svg',facecolor='white')
    plt.close(fig)
    for j,c in enumerate(COUNTS):
        print(c,'trial_totals',[row[j] for row in totals],'mean_total',statistics.mean(row[j] for row in totals),'mean_per_agent',statistics.mean(row[j] for row in averages))
    print(OUT/'total_and_average_tons.png')

if __name__=='__main__':main()
