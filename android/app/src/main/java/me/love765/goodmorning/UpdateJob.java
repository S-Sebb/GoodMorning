package me.love765.goodmorning;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/**
 * An hourly release check that Android batches with other work and runs only when online,
 * so updates are noticed even while the app stays open in the background for days.
 */
public class UpdateJob extends JobService {
    /** Job 1 was the daily check of earlier versions. */
    private static final int ID = 4;
    private static final long PERIOD = 60 * 60 * 1000L;

    static void schedule(Context context) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        scheduler.cancel(1);
        if (scheduler.getPendingJob(ID) != null) return;
        scheduler.schedule(new JobInfo.Builder(ID, new ComponentName(context, UpdateJob.class))
                .setPeriodic(PERIOD)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .build());
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            Updates.check(this);
            jobFinished(params, false);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
