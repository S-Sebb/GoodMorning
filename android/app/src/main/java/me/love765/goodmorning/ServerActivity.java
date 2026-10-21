package me.love765.goodmorning;

import android.app.Activity;
import android.os.Bundle;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import java.io.IOException;

/** First-launch server picker, also opened from the "Change server" launcher shortcut. */
public class ServerActivity extends Activity {
    private EditText address;
    private TextView status;
    private Button next;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(R.layout.server);
        address = findViewById(R.id.address);
        status = findViewById(R.id.status);
        next = findViewById(R.id.next);
        if (state == null) {
            String saved = Server.get(this);
            address.setText(saved == null ? Server.DEFAULT : saved);
        }
        next.setOnClickListener(view -> check());
        address.setOnEditorActionListener((view, action, event) -> {
            if (action != EditorInfo.IME_ACTION_GO) return false;
            check();
            return true;
        });
    }

    private void check() {
        String origin = Server.origin(address.getText().toString());
        if (origin == null) {
            show(R.string.server_error_address, true);
            return;
        }
        next.setEnabled(false);
        show(R.string.server_checking, false);
        new Thread(() -> {
            int problem;
            try {
                problem = Server.supportsApp(this, origin) ? 0 : R.string.server_error_unsupported;
            } catch (IOException | RuntimeException error) {
                problem = R.string.server_error_unreachable;
            }
            int result = problem;
            runOnUiThread(() -> {
                if (isFinishing()) return;
                next.setEnabled(true);
                if (result != 0) {
                    show(result, true);
                    return;
                }
                Server.set(this, origin);
                startActivity(Launcher.start(this));
                finish();
            });
        }).start();
    }

    private void show(int text, boolean error) {
        status.setText(text);
        status.setTextColor(getColor(error ? R.color.error : R.color.ink));
    }
}
