package me.love765.goodmorning;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** The periodic summary check, the extra checks while the account's work runs, and sending waiting notes; see {@link Sync}. */
public class SyncJob extends JobService {
    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            Sync.run(this);
            jobFinished(params, params.getJobId() == Notes.JOB && Notes.waiting(this));
            // Only now, as a check scheduled while this one still ran would be dropped.
            if (params.getJobId() == Sync.SOON && Sync.busy(this)) Sync.soon(this, true);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
