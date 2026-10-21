package me.love765.goodmorning;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** The periodic summary check; see {@link Sync#schedule}. */
public class SyncJob extends JobService {
    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            Sync.run(this);
            jobFinished(params, false);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
