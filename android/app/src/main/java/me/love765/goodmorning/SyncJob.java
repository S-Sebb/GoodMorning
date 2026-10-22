package me.love765.goodmorning;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** The periodic summary check, the extra checks while a briefing is prepared, and sending waiting notes; see {@link Sync}. */
public class SyncJob extends JobService {
    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            Sync.run(this);
            boolean again = params.getJobId() == Sync.SOON ? Sync.preparing(this) : params.getJobId() == Notes.JOB && Notes.waiting(this);
            jobFinished(params, again);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
