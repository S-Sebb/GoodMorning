package me.love765.goodmorning;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/**
 * A once-a-day release check that Android batches with other work and runs only when online,
 * so updates are noticed even while the app stays open in the background for days.
 */
public class UpdateJob extends JobService {
    private static final int ID = 1;

    static void schedule(Context context) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (scheduler.getPendingJob(ID) != null) return;
        scheduler.schedule(new JobInfo.Builder(ID, new ComponentName(context, UpdateJob.class))
                .setPeriodic(Updates.DAY)
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
