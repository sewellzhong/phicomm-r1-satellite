package dev.sewellzhong.r1probe.assist;

import java.util.Arrays;

/** Two-second playback reference. Conservative linear subtraction, never a silence gate. */
public final class PromptReference {
    private final short[] ring = new short[32000];
    private long written, head, headAt, endedAt;
    private boolean active;
    private int consecutive, previousDelay = -1;
    public volatile double correlation, beforeRms, afterRms;
    public volatile int delaySamples, matchedFrames, processedFrames, overBudgetFrames;
    public volatile long maxProcessNanos;
    public synchronized void start() {
        clear(); active=true; matchedFrames=processedFrames=overBudgetFrames=0;maxProcessNanos=0;
        correlation=beforeRms=afterRms=0; delaySamples=0;
    }
    public synchronized void append(byte[] bytes,int offset,int length,float gain) {
        if(!active) return;
        for(int i=offset;i<offset+length;i+=2) {
            short sample=(short)((bytes[i]&255)|(bytes[i+1]<<8));
            ring[(int)(written++%ring.length)]=(short)Math.round(sample*gain);
        }
    }
    public synchronized void position(long frames,long now) { if(active) {head=frames;headAt=now;} }
    public synchronized void finish(long now) { if(active) {head=written;headAt=now;endedAt=now;} }
    public synchronized void clear() {
        Arrays.fill(ring,(short)0);written=head=headAt=endedAt=0;active=false;consecutive=0;previousDelay=-1;
    }
    public synchronized void expire(long now) {
        if(active && endedAt!=0 && now-endedAt>1_000_000_000L) clear();
    }
    public synchronized void resetConfidence() { consecutive=0; previousDelay=-1; }
    private double coarseSum, coarsePower, fullSum, fullPower;
    private final double[] candidateScores=new double[4];
    private final long[] candidatePositions=new long[4];
    private double score(short[] frame,long start,int stride) {
        double x=0,xx=0,xy=0;
        int base=(int)(start%ring.length), n=320/stride;
        for(int i=0;i<320;i+=stride) {
            int index=base+i;if(index>=ring.length)index-=ring.length;
            double a=ring[index];x+=a;xx+=a*a;xy+=a*frame[i];
        }
        double y=stride==32 ? coarseSum : fullSum;
        double yy=stride==32 ? coarsePower : fullPower;
        xx-=x*x/n;xy-=x*y/n;
        // Rank squared correlation; avoid thousands of sqrt and 64-bit divisions per frame.
        return xx>1 && yy>1 && xy>0 ? xy*xy/(xx*yy) : 0;
    }
    public synchronized void process(short[] frame,long now) {
        if(frame.length!=320) throw new IllegalArgumentException("reference_frame_size");
        if(!active) return;
        if(endedAt!=0 && now-endedAt>1_000_000_000L) {clear();return;}
        if(headAt==0 || written<320) return;
        long started=System.nanoTime();
        // A capture read may lag actual sound. Search only the last 500 ms of rendered PCM.
        long projected=head+Math.max(0,(now-headAt)*16000/1_000_000_000L);
        long expected=projected-320;
        long low=Math.max(Math.max(0,written-ring.length),expected-8000);
        long high=Math.min(written-320,expected);
        coarseSum=coarsePower=fullSum=fullPower=0;
        for(int i=0;i<320;i++) {
            double v=frame[i];fullSum+=v;fullPower+=v*v;
            if((i&31)==0) {coarseSum+=v;coarsePower+=v*v;}
        }
        coarsePower-=coarseSum*coarseSum/10;fullPower-=fullSum*fullSum/320;
        Arrays.fill(candidateScores,0);Arrays.fill(candidatePositions,-1);
        for(long pos=low;pos<=high;pos++) {
            double score=score(frame,pos,32);
            for(int k=0;k<4;k++) if(score>candidateScores[k]) {
                for(int j=3;j>k;j--) {candidateScores[j]=candidateScores[j-1];candidatePositions[j]=candidatePositions[j-1];}
                candidateScores[k]=score;candidatePositions[k]=pos;break;
            }
        }
        double exact=0;long exactStart=-1;
        for(long candidate:candidatePositions) if(candidate>=0)
            for(long pos=Math.max(low,candidate-4);pos<=Math.min(high,candidate+4);pos++) {
                double score=score(frame,pos,1);
                if(score>exact) {exact=score;exactStart=pos;}
            }
        exact=Math.sqrt(Math.min(1,exact));
        correlation=exact;delaySamples=exactStart<0 ? -1 : (int)(expected-exactStart);
        double mean=0,power=0;for(short sample:frame){mean+=sample;power+=(double)sample*sample;}
        mean/=320;beforeRms=Math.sqrt(Math.max(0,power/320-mean*mean));afterRms=beforeRms;
        // Confidence must persist at a consistent delay; mismatches never erase user speech.
        if(exact>=.85 && (previousDelay<0 || Math.abs(delaySamples-previousDelay)<=320)) consecutive++;
        else consecutive=exact>=.85 ? 1 : 0;
        previousDelay=exact>=.85 ? delaySamples : -1;
        if(consecutive>=3 && exactStart>=0) {
            double rm=0,rr=0,rx=0;
            for(int i=0;i<320;i++) rm+=ring[(int)((exactStart+i)%ring.length)];rm/=320;
            for(int i=0;i<320;i++) {double v=ring[(int)((exactStart+i)%ring.length)]-rm;rr+=v*v;rx+=v*(frame[i]-mean);}
            double gain=rr>0 ? rx/rr : 0;
            double sum=0,square=0;
            for(int i=0;i<320;i++) {
                double residual=frame[i]-gain*(ring[(int)((exactStart+i)%ring.length)]-rm);
                frame[i]=(short)Math.max(-32768,Math.min(32767,Math.round(residual)));
                sum+=frame[i];square+=(double)frame[i]*frame[i];
            }
            afterRms=Math.sqrt(Math.max(0,square/320-(sum/320)*(sum/320)));matchedFrames++;
        }
        processedFrames++;long elapsed=System.nanoTime()-started;
        maxProcessNanos=Math.max(maxProcessNanos,elapsed);if(elapsed>20_000_000L)overBudgetFrames++;
    }
}
