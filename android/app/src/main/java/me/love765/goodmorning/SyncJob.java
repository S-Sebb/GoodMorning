package me.love765.goodmorning;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** The periodic summary check, and the extra checks while a briefing is prepared; see {@link Sync}. */
public class SyncJob extends JobService {
    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            Sync.run(this);
            jobFinished(params, params.getJobId() == Sync.SOON && Sync.preparing(this));
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
