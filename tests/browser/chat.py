"""Rendered mode switch and conversation flow using an isolated synthetic agent."""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect
from PIL import Image, ImageDraw


def check_composer(browser, address, artifacts):
    checks = []
    for width, motion in ((1440, 'no-preference'), (390, 'no-preference'), (320, 'reduce')):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion=motion)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(address + '/chat?mode=secretary')
        page.evaluate('document.fonts.ready')
        row = page.locator('.chat-input-row')
        text = page.get_by_label('Your message', exact=True)
        layout = 'node => [node.offsetLeft, node.offsetTop, node.offsetWidth, node.offsetHeight]'
        for edition, scheme in (('gm', 'classic'), ('gm', 'warm'), ('gn', 'classic')):
            text.fill('Keep this draft')
            page.locator('#new-conversation').focus()
            page.evaluate("([edition, scheme]) => { document.documentElement.dataset.edition = edition; document.documentElement.dataset.dayScheme = scheme; }", [edition, scheme])
            page.evaluate("async () => { await Promise.all(document.querySelector('.chat-input-row').getAnimations().map(a => a.finished)); }")
            before = row.evaluate(layout)
            plain = row.evaluate('node => getComputedStyle(node).borderColor')
            text.click()
            expect(text).to_be_focused()
            expect(text).to_have_css('outline-style', 'none')
            if motion != 'reduce':
                page.wait_for_function("() => document.querySelector('.chat-input-row').getAnimations().length > 0")
                transition = row.evaluate('''node => {
                    const animations = node.getAnimations();
                    animations.forEach(a => { a.pause(); a.currentTime = a.effect.getTiming().duration / 2; });
                    const middle = getComputedStyle(node).borderColor;
                    animations.forEach(a => a.finish());
                    return {middle, final: getComputedStyle(node).borderColor};
                }''')
                assert transition['middle'] not in (plain, transition['final']), transition
            else:
                assert row.evaluate('node => node.getAnimations().length') == 0
            accent = page.locator('.desk-symbol').evaluate('node => getComputedStyle(node).color')
            expect(row).to_have_css('border-color', accent)
            assert row.evaluate("node => getComputedStyle(node).boxShadow.endsWith('0px 0px 0px 1px inset')")
            assert row.evaluate(layout) == before, 'Focus moved or resized the composer'
            if motion != 'reduce':
                row.screenshot(path=str(artifacts / f'composer-focus-{edition}-{scheme}-{width}.png'))
            page.keyboard.press('Tab')
            expect(page.locator('#chat-send')).to_be_focused()
            expect(page.locator('#chat-send')).to_have_css('outline-style', 'solid')
            page.locator('#new-conversation').focus()
            page.evaluate("async () => { await Promise.all(document.querySelector('.chat-input-row').getAnimations().map(a => a.finished)); }")
            expect(row).to_have_css('border-color', plain)
            expect(text).to_have_value('Keep this draft')
            assert row.evaluate(layout) == before
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert not errors, errors
        checks.append({'width': width, 'motion': motion, 'palettes': 3, 'roundedFocus': True,
                       'animatedFocus': motion != 'reduce', 'layoutShift': False, 'keyboardFocus': True})
        page.close()
    return checks


def check_highlight(browser, address, artifacts):
    checks = []
    for width, motion in ((1440, 'no-preference'), (390, 'no-preference'), (320, 'reduce')):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion=motion, device_scale_factor=2)
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(address + '/chat?mode=secretary')
        expect(page.locator('#chat-send')).to_be_enabled()
        page.evaluate('document.fonts.ready')
        page.evaluate('messages => showMessages(messages)', [
            {'id': 'user', 'role': 'user', 'text': 'Review the confirmed project priorities.'},
            {'id': 'reply', 'role': 'assistant', 'text': '## Reviewing your plan\n\nKeeping **the confirmed work** in focus.'}
        ])
        scroll = page.locator('#chat-scroll')
        send = page.locator('#chat-send')
        geometry = 'node => [node.offsetWidth, node.offsetHeight, node.clientWidth, node.clientHeight]'
        def settle():
            page.evaluate("async () => { await Promise.all(document.querySelector('#chat-scroll').getAnimations().map(a => a.finished)); }")
        def sample_transition():
            if motion == 'reduce':
                assert scroll.evaluate('node => node.getAnimations().length') == 0
                return None
            page.wait_for_function("() => document.querySelector('#chat-scroll').getAnimations().length > 0")
            return scroll.evaluate('''node => {
                const animations = node.getAnimations();
                animations.forEach(a => { a.pause(); a.currentTime = a.effect.getTiming().duration / 2; });
                const middle = getComputedStyle(node).borderColor;
                animations.forEach(a => a.finish());
                return {middle, final: getComputedStyle(node).borderColor};
            }''')
        for edition, scheme in (('gm', 'classic'), ('gm', 'warm'), ('gn', 'classic')):
            page.evaluate("([edition, scheme]) => { clearTimeout(themeTimer); document.documentElement.dataset.edition = edition; document.documentElement.dataset.dayScheme = scheme; state = 'idle'; showActivity(); }", [edition, scheme])
            settle()
            before = scroll.evaluate(geometry)
            plain = scroll.evaluate('node => getComputedStyle(node).borderColor')
            accent = page.locator('.desk-symbol').evaluate('node => getComputedStyle(node).color')
            for side in ('top', 'right', 'bottom', 'left'):
                expect(send).to_have_css(f'border-{side}-width', '0px')
            assert send.evaluate('node => [node.offsetWidth, node.offsetHeight]') == [44, 44]
            send.hover(); expect(send).to_have_css('border-top-width', '0px')
            send.focus(); expect(send).to_have_css('outline-style', 'solid')
            page.locator('#chat-attach').focus()
            page.mouse.move(0, 0)
            page.evaluate("state = 'running'; showActivity()")
            expect(scroll).to_have_class('is-working')
            growing = sample_transition()
            expect(scroll).to_have_css('border-color', accent)
            assert scroll.evaluate("node => getComputedStyle(node).boxShadow.endsWith('0px 0px 0px 1px inset')")
            assert scroll.evaluate(geometry) == before
            page.locator('.conversation-panel').screenshot(path=str(artifacts / f'reply-highlight-{edition}-{scheme}-{width}-working.png'))
            page.evaluate("state = 'idle'; showActivity()")
            fading = sample_transition()
            expect(scroll).to_have_class('')
            expect(scroll).to_have_css('border-color', plain)
            if motion != 'reduce':
                for transition in (growing, fading):
                    assert transition['middle'] not in (plain, accent), transition
            assert scroll.evaluate(geometry) == before
            page.locator('.conversation-panel').screenshot(path=str(artifacts / f'reply-highlight-{edition}-{scheme}-{width}-idle.png'))
            for status in ('waiting', 'queued', 'unavailable'):
                page.evaluate('status => { state = status; showActivity(); }', status)
                expect(scroll).to_have_class('')
            checks.append({'width': width, 'edition': edition, 'scheme': scheme, 'borderlessSend': True,
                           'workingHighlight': True, 'fadesToQuiet': True, 'animated': motion != 'reduce', 'layoutShift': False})
        assert not errors, errors
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.close()
    return checks


def check_motion(browser, address, artifacts):
    checks = []
    for width, motion in ((1440, 'no-preference'), (390, 'no-preference'), (390, 'reduce')):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion=motion)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        pending = []
        queue = []
        messages = []
        status = {'mode': 'secretary', 'state': 'running', 'language': 'en', 'label': 'Your secretary is working',
                  'messages': messages, 'forms': [], 'permissions': []}
        page.route('**/api/chats', lambda route: pending.append(route) if route.request.method == 'POST'
                   else route.fulfill(json={'defaultMode': 'secretary', 'connected': True, 'chats': []}))
        page.route('**/api/chats/*', lambda route: route.fulfill(json=status))
        page.route('**/api/queue', lambda route: route.fulfill(json={'queue': queue, 'depth': len(queue)}))
        page.add_init_script("""window.messageEntrances = 0; window.messageFrames = [];
            document.addEventListener('animationstart', event => {
                if (event.animationName !== 'chat-message-enter' || !event.target.matches('.chat-message')) return;
                window.messageEntrances++;
                const frames = []; window.messageFrames.push(frames);
                const sample = () => {
                    frames.push(Number(getComputedStyle(event.target).opacity));
                    if (event.target.getAnimations().length) requestAnimationFrame(sample);
                };
                requestAnimationFrame(sample);
            });""")
        page.goto(address + '/chat?mode=secretary')
        expect(page.get_by_role('button', name='Start conversation', exact=True)).to_be_enabled()
        expect(page.locator('#chat-empty')).to_be_visible()
        page.get_by_label('Your message', exact=True).fill('Plan a calm day')
        with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/chats')):
            page.get_by_role('button', name='Start conversation', exact=True).click()
        expect(page.locator('#chat-status')).to_have_text('Sending your message')
        expect(page.locator('#chat-empty')).to_be_hidden()
        expect(page.locator('.chat-message')).to_have_count(0)
        status_gap = page.locator('#chat-status').evaluate('node => node.getBoundingClientRect().top - document.querySelector("#chat-scroll").getBoundingClientRect().top')
        assert 0 <= status_gap <= 48, status_gap
        page.locator('.conversation-panel').screenshot(path=str(artifacts / f'chat-immediate-send-{width}-{motion}.png'))
        expect(page.locator('#chat-scroll')).to_have_class('is-working')
        expect(page.locator('#chat-send')).to_have_css('border-top-width', '0px')
        expect(page.locator('.chat-activity-dots')).to_be_visible()
        assert page.locator('.chat-activity-dots').get_attribute('aria-hidden') == 'true'
        dot_animation = page.locator('.chat-activity-dots span').first.evaluate(
            "node => getComputedStyle(node).animationName")
        assert dot_animation == ('none' if motion == 'reduce' else 'chat-activity')
        pending.pop().fulfill(json={'accepted': True})
        expect(page.locator('#chat-status')).to_have_text('Your secretary is working')
        expect(page.locator('#chat-empty')).to_be_hidden()
        expect(page.locator('.chat-message')).to_have_count(0)
        messages.append({'id': 'user-1', 'role': 'user', 'text': 'Plan a calm day'})
        page.evaluate('pollChat()')
        expect(page.locator('#chat-scroll')).to_have_class('is-working')
        expect(page.get_by_role('log')).to_contain_text('Plan a calm day')
        page.screenshot(path=str(artifacts / f'chat-working-{width}-{motion}.png'), full_page=True)
        messages.append({'id': 'assistant-1', 'role': 'assistant', 'text': 'Let’s leave room to breathe.\nOne priority at a time.'})
        status.update(state='idle', label='Ready for your reply')
        page.evaluate('pollChat()')
        expect(page.get_by_role('log')).to_contain_text('One priority at a time.')
        expect(page.locator('.chat-activity-dots')).to_be_hidden()
        expect(page.locator('#chat-scroll')).to_have_class('')
        expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
        page.evaluate("""async () => {
            await Promise.all([...document.querySelectorAll('.chat-message')].flatMap(
                node => node.getAnimations().map(animation => animation.finished)));
        }""")
        entrances = page.evaluate('window.messageEntrances')
        assert entrances == (0 if motion == 'reduce' else 2), entrances
        frames = page.evaluate('window.messageFrames')
        if motion != 'reduce':
            assert all(any(0 < opacity < 1 for opacity in samples) for samples in frames), frames
        assert page.locator('.message-enter').count() == 0
        page.evaluate("messageSignature = ''; pollChat()")
        assert page.evaluate('window.messageEntrances') == entrances
        assert page.locator('.chat-message').count() == 2
        page.reload()
        expect(page.get_by_role('log')).to_contain_text('One priority at a time.')
        assert page.locator('.message-enter').count() == 0
        assert page.evaluate('window.messageEntrances') == 0

        # Queued requests stay quiet, then show activity when the queue releases them.
        page.get_by_role('button', name='New conversation', exact=True).click()
        page.get_by_label('Your message', exact=True).fill('A queued request')
        with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/chats')):
            page.get_by_role('button', name='Start conversation', exact=True).click()
        queued_id = pending[0].request.post_data_json['id']
        queue.append({'work': 'chat', 'chat': queued_id, 'position': 1})
        pending.pop().fulfill(json={'queued': True, 'position': 1, 'depth': 1})
        expect(page.locator('#chat-status')).to_contain_text('You are #1 in line')
        expect(page.locator('#chat-empty')).to_be_hidden()
        expect(page.locator('#chat-scroll')).to_have_class('')
        expect(page.locator('.chat-activity-dots')).to_be_hidden()
        queue.clear()
        status.update(state='running', label='Your secretary is working')
        page.evaluate('pollQueue()')
        expect(page.locator('#chat-status')).to_have_text('Your secretary is working')
        expect(page.locator('.chat-activity-dots')).to_be_visible()
        page.get_by_role('button', name='New conversation', exact=True).click()
        expect(page.locator('#chat-status')).to_be_empty()
        expect(page.locator('#chat-empty')).to_be_visible()
        expect(page.locator('#chat-scroll')).to_have_class('')

        # A rejected send stops activity and preserves the unsent draft.
        page.get_by_label('Your message', exact=True).fill('Keep this draft')
        with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/chats')):
            page.get_by_role('button', name='Start conversation', exact=True).click()
        pending.pop().fulfill(status=400, json={'error': 'Synthetic rejection'})
        expect(page.get_by_role('alert')).to_have_text('Synthetic rejection')
        expect(page.locator('#chat-empty')).to_be_visible()
        expect(page.locator('#chat-scroll')).to_have_class('')
        expect(page.locator('.chat-activity-dots')).to_be_hidden()
        expect(page.get_by_label('Your message', exact=True)).to_have_value('Keep this draft')
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert not errors, errors
        checks.append({'width': width, 'motion': motion, 'messageEntrances': entrances,
                       'sampledAnimationFrames': [len(samples) for samples in frames],
                       'immediateFeedback': True, 'welcomeHidesBeforeFirstMessage': True,
                       'welcomeRestoredOnRejectedSend': True, 'queueRelease': True, 'historyReplay': False, 'pageErrors': 0})
        page.close()
    return checks


def check_uploads(browser, address, artifacts):
    checks = []
    for width in (1440, 390, 320):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(address + '/chat?mode=secretary')
        expect(page.get_by_role('button', name='Attach files', exact=True)).to_be_enabled()
        with page.expect_file_chooser() as chooser:
            page.get_by_role('button', name='Attach files', exact=True).click()
        chooser.value.set_files([{'name': '资料 <img>.txt', 'mimeType': 'text/plain', 'buffer': b'Synthetic notes'},
                                 {'name': 'remove.txt', 'mimeType': 'text/plain', 'buffer': b'Remove this'}])
        expect(page.locator('#chat-attachments')).to_contain_text('资料 <img>.txt')
        page.get_by_role('button', name='Remove remove.txt', exact=True).click()
        expect(page.locator('#chat-attachments .attachment-chip')).to_have_count(1)
        page.get_by_role('radio', name='To-do', exact=True).click()
        expect(page.locator('#chat-attachments .attachment-chip')).to_have_count(0)
        page.get_by_role('radio', name='Secretary', exact=True).click()
        expect(page.locator('#chat-attachments .attachment-chip')).to_have_count(1)
        assert page.locator('#chat-attachments img').count() == 0
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(artifacts / f'attachments-{width}.png'), full_page=True)
        with page.expect_response('**/api/chat-uploads/*') as uploaded:
            page.get_by_role('button', name='Start conversation', exact=True).click()
        assert uploaded.value.status == 201
        expect(page.get_by_role('log')).to_contain_text('资料 <img>.txt')
        expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
        expect(page.locator('#chat-attachments .attachment-chip')).to_have_count(0)
        page.reload()
        expect(page.get_by_role('log')).to_contain_text('资料 <img>.txt')
        page.locator('#chat-files').set_input_files({'name': 'follow-up.txt', 'mimeType': 'text/plain', 'buffer': b'Follow-up'})
        page.get_by_role('button', name='Send reply', exact=True).click()
        expect(page.get_by_role('log')).to_contain_text('follow-up.txt')
        expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
        page.get_by_role('button', name='New conversation', exact=True).click()
        page.get_by_role('radio', name='Secretary', exact=True).click()
        requests = []
        page.on('request', lambda request: requests.append(request) if request.method == 'POST' else None)
        page.route('**/api/chat-uploads/*', lambda route: route.fulfill(status=413,
                   json={'error': 'Files must be 50 MB or smaller.'}), times=1)
        page.locator('#chat-files').set_input_files({'name': 'keep.txt', 'mimeType': 'text/plain', 'buffer': b'Keep draft'})
        page.get_by_role('button', name='Start conversation', exact=True).click()
        expect(page.get_by_role('alert')).to_have_text('Files must be 50 MB or smaller.')
        expect(page.locator('#chat-attachments')).to_contain_text('keep.txt')
        expect(page.get_by_role('button', name='Start conversation', exact=True)).to_be_enabled()
        assert not any(request.url.endswith('/api/chats') for request in requests)
        page.get_by_role('button', name='Remove keep.txt', exact=True).click()
        if width == 1440:
            dropped = page.evaluate_handle("""() => {
                const transfer = new DataTransfer();
                transfer.items.add(new File(['Dropped synthetic notes'], 'dropped.txt', {type: 'text/plain'}));
                return transfer;
            }""")
            page.locator('#chat-text').dispatch_event('dragenter', {'dataTransfer': dropped})
            expect(page.locator('#chat-compose')).to_have_class('is-dragging')
            page.locator('#chat-text').dispatch_event('dragover', {'dataTransfer': dropped})
            page.locator('#chat-text').dispatch_event('drop', {'dataTransfer': dropped})
            expect(page.locator('#chat-compose')).not_to_have_class('is-dragging')
            expect(page.locator('#chat-attachments')).to_contain_text('dropped.txt')
            page.get_by_role('button', name='Start conversation', exact=True).click()
            expect(page.get_by_role('log')).to_contain_text('dropped.txt')
            expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
            page.get_by_role('button', name='New conversation', exact=True).click()
            page.get_by_role('radio', name='Secretary', exact=True).click()
            page.evaluate("""() => {
                const input = document.querySelector('#chat-files');
                const transfer = new DataTransfer();
                transfer.items.add(new File([new Uint8Array(50 * 1024 * 1024 + 1)], 'oversize.txt'));
                input.files = transfer.files;
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }""")
            expect(page.get_by_role('alert')).to_have_text('Files must be 50 MB or smaller.')
            expect(page.locator('#chat-attachments .attachment-chip')).to_have_count(0)
        assert not errors, errors
        assert page.evaluate("localStorage.length === 0 && Object.values(sessionStorage).every(raw => Object.keys(JSON.parse(raw)).sort().join(',') === 'away,chat,draft,resume')")
        checks.append({'width': width, 'fileOnlySend': True, 'followUp': True, 'refresh': True,
                       'draftRemoval': True, 'rejectedUploadDoesNotDispatch': True,
                       'dragDrop': width == 1440, 'overflow': False, 'pageErrors': 0})
        page.close()
    return checks


def check_images(browser, address, artifacts):
    image = Image.new('RGB', (640, 400), '#ddebe5')
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 60, 580, 340), fill='#4d766b')
    draw.text((100, 180), 'Synthetic chat image', fill='white')
    buffer = io.BytesIO(); image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode()
    checks = []
    for width in (1440, 390, 320):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce',
                                permissions=['clipboard-read', 'clipboard-write'])
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(address + '/chat?mode=secretary')
        expect(page.locator('#chat-attach')).to_be_enabled()
        text = page.locator('#chat-text')
        text.fill('Caption stays here')
        page.evaluate('''async encoded => {
            const bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
            await navigator.clipboard.write([new ClipboardItem({'image/png': new Blob([bytes], {type:'image/png'})})]);
        }''', encoded)
        text.focus(); page.keyboard.press('Control+V')
        preview = page.locator('#chat-attachments .attachment-preview')
        expect(preview).to_have_count(1)
        expect(text).to_have_value('Caption stays here')
        page.wait_for_function('() => document.querySelector("#chat-attachments img").naturalWidth === 640')
        source = preview.locator('img').get_attribute('src')
        name = preview.locator('img').get_attribute('alt')
        assert source.startswith('blob:')
        preview.click()
        dialog = page.get_by_role('dialog', name='Image preview')
        expect(dialog).to_be_visible()
        expect(page.get_by_role('button', name='Close image')).to_be_focused()
        assert dialog.locator('img').bounding_box()['width'] > preview.locator('img').bounding_box()['width']
        page.keyboard.press('Escape'); expect(dialog).not_to_be_visible()
        expect(preview).to_be_focused()
        page.get_by_role('radio', name='To-do', exact=True).click()
        expect(preview).to_have_count(0)
        page.get_by_role('radio', name='Secretary', exact=True).click()
        expect(preview).to_have_count(1)
        assert preview.locator('img').get_attribute('src') == source
        page.locator('.conversation-panel').screenshot(path=str(artifacts / f'image-draft-{width}.png'))
        page.get_by_role('button', name='Start conversation', exact=True).click()
        expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
        saved = page.locator('.message-attachments .attachment-preview')
        expect(saved).to_have_count(1)
        page.wait_for_function('() => document.querySelector(".message-attachments img").naturalWidth === 640')
        expect(page.locator('.message-attachments .attachment-name')).to_have_count(0)
        expect(saved).to_have_css('border-top-width', '0px')
        expect(saved).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
        box = saved.locator('img').bounding_box()
        assert abs(box['width'] / box['height'] - 1.6) < .01, box
        url = saved.locator('img').get_attribute('src')
        assert url.startswith('/api/chat-uploads/') and url.endswith('/image')
        assert page.evaluate('async source => { try { await fetch(source); return false; } catch { return true; } }', source)
        page.reload()
        expect(saved).to_have_count(1)
        page.wait_for_function('() => document.querySelector(".message-attachments img").naturalWidth === 640')
        saved.click(); expect(dialog).to_be_visible()
        page.wait_for_function('() => document.querySelector(".chat-image-dialog img").naturalWidth === 640')
        assert dialog.locator('img').bounding_box()['width'] > 160
        assert dialog.bounding_box()['width'] <= width - 30
        page.screenshot(path=str(artifacts / f'image-enlarged-{width}.png'))
        page.get_by_role('button', name='Close image').click(); expect(dialog).not_to_be_visible()
        expect(saved).to_be_focused()
        page.locator('.conversation-panel').screenshot(path=str(artifacts / f'image-inline-{width}.png'))
        # Normal text paste remains native. Image paste while working is allowed for interrupts.
        page.evaluate('navigator.clipboard.writeText(" pasted text")')
        text.fill('Existing'); text.focus(); text.press('End'); page.keyboard.press('Control+V')
        expect(text).to_have_value('Existing pasted text')
        page.locator('#chat-files').set_input_files({'name': name, 'mimeType': 'image/png', 'buffer': buffer.getvalue()})
        removed_source = preview.locator('img').get_attribute('src')
        page.get_by_role('button', name='Remove ' + name, exact=True).click()
        expect(preview).to_have_count(0)
        assert page.evaluate('async source => { try { await fetch(source); return false; } catch { return true; } }', removed_source)
        page.evaluate('''() => {
            state = 'running'; composeState();
            const transfer = new DataTransfer();
            transfer.items.add(new File(['interrupt'], 'interrupt.png', {type:'image/png'}));
            document.querySelector('#chat-text').dispatchEvent(new ClipboardEvent('paste', {clipboardData:transfer, bubbles:true, cancelable:true}));
        }''')
        expect(preview).to_have_count(1)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert not errors, errors
        checks.append({'width': width, 'realClipboardPaste': True, 'draftPreview': True, 'savedPreview': True,
                       'enlargeAndClose': True, 'reload': True, 'draftRestored': True, 'urlsReleased': True})
        page.close()
    return checks


def check_question_history(browser, address, artifacts):
    checks = []
    for width, answer in ((1440, 'London'), (390, 'My typed city <img>')):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(address + '/chat?mode=initialize')
        page.get_by_role('button', name='Start initialization', exact=True).click()
        expect(page.get_by_role('heading', name='Confirm your location')).to_be_visible()
        if answer == 'London':
            page.get_by_role('radio', name='London', exact=True).check()
        else:
            page.get_by_placeholder('Or write your own answer').fill(answer)
        page.get_by_role('button', name='Send answer', exact=True).click()
        expect(page.get_by_role('heading', name='Permission needed')).to_be_visible()
        page.get_by_role('button', name='Decline', exact=True).click()
        expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
        expect(page.locator('.chat-message.question')).to_contain_text('Confirm your location')
        expect(page.locator('.chat-message.answer')).to_contain_text('City: ' + answer)
        page.reload()
        expect(page.locator('.chat-message.question')).to_have_count(1)
        expect(page.locator('.chat-message.answer')).to_have_count(1)
        expect(page.locator('.chat-message.answer')).to_contain_text('City: ' + answer)
        assert page.get_by_role('log').locator('.message-text img, .message-attachments img').count() == 0
        assert page.locator('#chat-questions .agent-form').count() == 0
        roles = page.locator('.chat-message').evaluate_all('nodes => nodes.map(node => node.className)')
        assert 'question' in roles[-3] and 'answer' in roles[-2], roles
        page.screenshot(path=str(artifacts / f'question-history-{width}.png'), full_page=True)
        assert page.evaluate("localStorage.length === 0 && Object.values(sessionStorage).every(raw => Object.keys(JSON.parse(raw)).sort().join(',') === 'away,chat,draft,resume')")
        assert not errors, errors
        checks.append({'width': width, 'answer': 'selected' if answer == 'London' else 'typed',
                       'questionSaved': True, 'answerSaved': True, 'refresh': True, 'pageErrors': 0})
        page.close()
    return checks


def check_waiting_reply_queue(browser, address, artifacts):
    page = browser.new_page(viewport={'width':390,'height':844}, reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(address+'/chat?mode=initialize')
        page.get_by_role('button',name='Start initialization',exact=True).click()
        expect(page.get_by_role('heading',name='Confirm your location')).to_be_visible()
        expect(page.locator('#chat-status')).to_contain_text('Take your time.')
        page.reload()
        expect(page.get_by_role('heading',name='Confirm your location')).to_be_visible()
        page.get_by_role('radio',name='London',exact=True).check()
        chat=page.evaluate('chat')
        reply=f'/api/chats/{chat}/form/form_city/reply'
        queued={'queue':[], 'depth':0}
        page.route('**/api/queue',lambda route:route.fulfill(json=queued))
        def enqueue(route):
            queued['queue']=[{'work':'reply','chat':chat,'position':1}];queued['depth']=1
            route.fulfill(status=202,json={'queued':True,'chat':chat,'position':1,'depth':1})
        page.route('**'+reply,enqueue,times=1)
        page.get_by_role('button',name='Send answer',exact=True).click()
        expect(page.locator('#chat-status')).to_contain_text('In queue')
        page.reload()
        expect(page.locator('#chat-status')).to_contain_text('In queue')
        expect(page.get_by_role('button',name='Send answer',exact=True)).to_have_count(0)
        config=json.loads(page.locator('#chat-config').get_attribute('data-config'))
        receipt=page.request.post(address+reply,data={'answer':{'city':'London'}},
            headers={'Origin':address,'X-Briefing-CSRF':config['csrf']})
        assert receipt.ok
        queued['queue']=[];queued['depth']=0
        expect(page.get_by_role('heading',name='Permission needed')).to_be_visible()
        page.get_by_role('button',name='Decline',exact=True).click()
        expect(page.get_by_role('button',name='Send reply',exact=True)).to_be_enabled()
        expect(page.locator('.chat-message.answer')).to_contain_text('City: London')
        page.screenshot(path=str(artifacts/'queued-answer-resumed-mobile.png'),full_page=True)
        assert not errors,errors
    finally:
        page.close()


def check_scroll(browser, address, artifacts):
    checks = []
    for width in (1440, 768, 390, 320):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        messages = [{'id': 'first', 'role': 'user', 'text': 'Start at the top.'}]
        status = {'mode': 'secretary', 'state': 'running', 'language': 'en', 'label': 'Your secretary is working',
                  'messages': messages, 'forms': [], 'permissions': []}
        page.route('**/api/chats/*', lambda route: route.fulfill(json=status))
        page.goto(address + '/chat?id=' + 'f' * 32)
        expect(page.get_by_role('log')).to_contain_text('Start at the top.')
        geometry = """() => {
            const scroll = document.querySelector('#chat-scroll');
            const panel = document.querySelector('#conversation');
            const compose = document.querySelector('#chat-compose');
            return {height: scroll.clientHeight, content: scroll.scrollHeight, top: scroll.scrollTop,
                pageHeight: document.documentElement.scrollHeight, pageTop: scrollY,
                panelHeight: panel.offsetHeight, composeTop: compose.offsetTop};
        }"""
        baseline = page.evaluate(geometry)
        top_gap = page.locator('.chat-message').first.evaluate("node => node.getBoundingClientRect().top - document.querySelector('#chat-scroll').getBoundingClientRect().top")
        assert 0 <= top_gap <= 24, top_gap
        messages.extend({'id': f'reply-{index}', 'role': 'assistant', 'text': f'Reply {index}\nA calm, useful update.'}
                        for index in range(35))
        page.evaluate('pollChat()')
        expect(page.get_by_role('log')).to_contain_text('Reply 34')
        page.wait_for_function('() => nearLatest()')
        grown = page.evaluate(geometry)
        for key in ('height', 'pageHeight', 'panelHeight', 'composeTop', 'pageTop'):
            assert baseline[key] == grown[key], (key, baseline, grown)
        assert grown['content'] > grown['height']
        assert page.locator('#chat-scroll').evaluate("node => getComputedStyle(node).overflowY") == 'auto'
        page.evaluate("document.querySelector('#chat-scroll').scrollTop = 0")
        expect(page.get_by_role('button', name='Jump to latest')).to_be_visible()
        messages.append({'id': 'new-reply', 'role': 'assistant', 'text': 'New reply while reading history.'})
        page.evaluate('pollChat()')
        expect(page.get_by_role('log')).to_contain_text('New reply while reading history.')
        assert page.evaluate(geometry)['top'] == 0
        page.get_by_role('button', name='Jump to latest').click()
        page.wait_for_function('() => nearLatest()')
        expect(page.get_by_role('button', name='Jump to latest')).to_be_hidden()

        # New question forms stay inside the bounded area, including long forms.
        status['forms'] = [{'id': 'long-form', 'title': 'Choose a schedule source', 'fields': [
            {'key': 'source', 'type': 'string', 'title': 'Source', 'custom': True,
             'options': [{'value': str(index), 'label': f'Source {index}'} for index in range(12)]}]}]
        status.update(state='waiting', label='Your secretary needs your answer')
        page.evaluate('pollChat()')
        expect(page.get_by_role('heading', name='Choose a schedule source')).to_be_visible()
        assert page.evaluate(geometry)['panelHeight'] == baseline['panelHeight']
        page.locator('#chat-scroll').scroll_into_view_if_needed()
        page.screenshot(path=str(artifacts / f'bounded-chat-{width}.png'), full_page=True)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert not errors, errors
        checks.append({'width': width, 'fixedHeight': grown['height'], 'topAligned': True,
                       'pageDoesNotGrow': True, 'readingPositionPreserved': True, 'jumpToLatest': True,
                       'longQuestionContained': True, 'pageErrors': 0})
        page.close()
    return checks


def check_autogrow(browser, address, artifacts):
    checks = []
    for width,height in ((1440,900),(768,900),(390,844),(320,568)):
        page=browser.new_page(viewport={'width':width,'height':height},reduced_motion='reduce',has_touch=width<700)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(address+'/chat?mode=secretary')
        expect(page.locator('#chat-send')).to_be_enabled()
        assert page.evaluate("Boolean(document.querySelector('#conversation-history').compareDocumentPosition(document.querySelector('#new-conversation')) & Node.DOCUMENT_POSITION_FOLLOWING)")
        if width<700:
            page.evaluate("window.scrollTo({top: document.querySelector('#conversation').getBoundingClientRect().top + scrollY, behavior: 'instant'})")
        expect(page.locator('#chat-send')).to_be_in_viewport()
        panel=page.locator('.conversation-panel');composer=page.locator('.chat-input-row')
        text=page.locator('#chat-text');scroll=page.locator('#chat-scroll')
        original=panel.bounding_box();bottom=composer.bounding_box()['y']+composer.bounding_box()['height']
        original_scroll=scroll.bounding_box()['height']
        if width>700:
            assert page.evaluate('document.documentElement.scrollHeight-innerHeight')<=1
            assert 100<original['y']<300,original
            assert original['y']+original['height']<=height+1,original
        else:
            assert abs(original['y']-0)<1,original
            panel_top = panel.evaluate('node => node.getBoundingClientRect().top + scrollY')
            assert abs(original['height']-max(240,height-panel_top-12))<1,original
        for lines in range(1,9):
            text.fill('\n'.join('Line '+str(index) for index in range(lines)))
            expect(text).to_have_css('height',str(24*min(lines,5))+'px')
            box=composer.bounding_box()
            assert abs(box['y']+box['height']-bottom)<1,box
            assert panel.bounding_box()==original,'Typing moved the outer chat panel'
            assert abs(scroll.bounding_box()['height']-(original_scroll-max(0,24*min(lines,5)-44)))<1
            if lines>5:
                assert text.evaluate('node => Math.abs(node.scrollTop-(node.scrollHeight-node.clientHeight))<1'),'Last draft line is not visible'
        assert text.evaluate('node => node.scrollHeight>node.clientHeight && getComputedStyle(node).overflowY==="auto" && node.clientHeight/parseFloat(getComputedStyle(node).lineHeight)===5')
        text.press('End')
        page.locator('.conversation-panel').screenshot(path=str(artifacts/f'five-line-composer-{width}.png'))
        text.fill('Line one\nLine two');expect(text).to_have_css('height','48px')
        page.get_by_role('radio',name='To-do',exact=True).click();expect(text).to_have_css('height','24px')
        page.get_by_role('radio',name='Secretary',exact=True).click()
        expect(text).to_have_value('Line one\nLine two');expect(text).to_have_css('height','48px')
        text.fill('word '*20)
        page.set_viewport_size({'width':320,'height':568});expect(text).to_have_css('height','120px')
        page.set_viewport_size({'width':1440,'height':900});expect(text).to_have_css('height','48px')
        expect(text).to_have_value('word '*20)
        text.fill('Reply line one\nReply line two')
        page.get_by_role('button',name='Start conversation',exact=True).click()
        expect(text).to_have_value('');expect(text).to_have_css('height','24px')
        expect(page.get_by_role('button',name='Send reply',exact=True)).to_be_enabled()
        # Use a stable status response rather than injecting DOM content that an
        # outstanding real-fixture status request can immediately replace.
        page.wait_for_function('() => !polling && !sending')
        page.route('**/api/chats/'+page.evaluate('chat'),lambda route:route.fulfill(json={
            'mode':'secretary','state':'idle','language':'en','label':'Ready for your reply',
            'forms':[],'permissions':[], 'messages':[{'id':'long','role':'assistant',
                'text':'Synthetic reading position.\n'*200}]}))
        page.evaluate('pollChat()')
        expect(scroll).to_contain_text('Synthetic reading position.')
        scroll.evaluate('node => node.scrollTop=120')
        before_reading=scroll.evaluate('node => ({top:node.scrollTop,height:node.scrollHeight,client:node.clientHeight})')
        assert abs(before_reading['top']-120)<1,before_reading
        text.fill('Keep reading\nEarlier messages\nWhile typing')
        after_reading=scroll.evaluate('node => ({top:node.scrollTop,height:node.scrollHeight,client:node.clientHeight,text:node.innerText.slice(0,120)})')
        assert abs(after_reading['top']-120)<1,{'width':width,'before':before_reading,'after':after_reading}
        assert not errors,errors
        checks.append({'width':width,'height':height,'upwardGrowth':True,'fiveLineCap':True,'draftRestored':True,
                       'responsiveReflow':True,'readingPositionPreserved':True,'newConversationBelowHistory':True})
        page.close()
    return checks


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-chat-browser-') as directory:
        root = Path(directory)
        profile=root/'profile.md'
        profile.write_text('secretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\n')
        (root / 'preserved-record.txt').write_text('Preserved synthetic evidence')
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / 'test_briefing_chat.py'),
                                    '--serve-fixture', directory], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                composer_checks = check_composer(browser, address, artifacts)
                autogrow_checks = check_autogrow(browser, address, artifacts)
                highlight_checks = check_highlight(browser, address, artifacts)
                motion_checks = check_motion(browser, address, artifacts)
                upload_checks = check_uploads(browser, address, artifacts)
                image_checks = check_images(browser, address, artifacts)
                # Setup questions and the readiness transition use a new profile;
                # composer/layout checks above deliberately use a ready profile.
                profile.unlink()
                question_checks = check_question_history(browser, address, artifacts)
                check_waiting_reply_queue(browser, address, artifacts)
                scroll_checks = check_scroll(browser, address, artifacts)
                for width in (1440, 768, 390, 320):
                    page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                    if width == 1440:
                        for kind in ('gm','gn'):
                            page.goto(address + '/' + kind + '.html')
                            expect(page.get_by_role('link',name='Initialize my secretary')).to_be_visible()
                            expect(page.locator('#generate')).to_have_count(0)
                            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                            page.screenshot(path=str(artifacts/(kind+'-initialize-button-desktop.png')),full_page=True)
                        page.get_by_role('link',name='Initialize my secretary').click()
                        expect(page.get_by_role('radio',name='Initialize',exact=True)).to_have_attribute('aria-checked','true')
                        assert not list((root/'browser-chats').glob('*.context.json'))
                    page.goto(address + '/chat')
                    modes = page.get_by_role('radiogroup', name='Secretary mode')
                    expect(modes.get_by_role('radio')).to_have_count(1 if width == 1440 else 3)
                    initial = 'Initialize' if width == 1440 else 'Secretary'
                    expect(modes.get_by_role('radio', name=initial, exact=True)).to_have_attribute('aria-checked', 'true')
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    if width == 1440:
                        page.screenshot(path=str(artifacts / 'initialization-desktop.png'), full_page=True)
                        page.get_by_role('button', name='Start initialization', exact=True).click()
                        expect(page.get_by_role('heading', name='Confirm your location')).to_be_visible()
                        page.get_by_placeholder('Or write your own answer').fill('London, please')
                        with page.expect_response('**/api/chats/*'):
                            page.evaluate('pollChat()')
                        expect(page.get_by_placeholder('Or write your own answer')).to_have_value('London, please')
                        page.reload()
                        expect(page.get_by_role('heading', name='Confirm your location')).to_be_visible()
                        page.get_by_text('London', exact=True).click()
                        page.get_by_role('button', name='Send answer', exact=True).click()
                        expect(page.get_by_role('heading', name='Permission needed')).to_be_visible()
                        page.get_by_role('button', name='Allow once', exact=True).click()
                        expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
                        expect(page.get_by_role('log')).to_contain_text('Synthetic setup saved')
                        page.get_by_role('button', name='New conversation', exact=True).click()
                        expect(modes.get_by_role('radio', name='Secretary', exact=True)).to_have_attribute('aria-checked', 'true')
                    # Mode switch changes only the draft, not the saved conversation.
                    modes.get_by_role('radio', name='To-do', exact=True).click()
                    page.get_by_label('Your message', exact=True).fill('Capture a synthetic task')
                    modes.get_by_role('radio', name='Eureka', exact=True).click()
                    page.get_by_label('Your message', exact=True).fill('Capture a synthetic idea')
                    modes.get_by_role('radio', name='To-do', exact=True).click()
                    expect(page.get_by_label('Your message', exact=True)).to_have_value('Capture a synthetic task')
                    page.get_by_role('button', name='Save to-do', exact=True).click()
                    expect(page.get_by_role('log')).to_contain_text('Synthetic reply')
                    assert page.get_by_role('log').locator('.message-text img, .message-attachments img').count() == 0
                    expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
                    chat_url = page.url
                    page.reload()
                    expect(modes.get_by_role('radio', name='To-do', exact=True)).to_have_attribute('aria-checked', 'true')
                    expect(page.get_by_role('log')).to_contain_text('Capture a synthetic task')
                    page.get_by_label('Your message', exact=True).fill('A synthetic clarification')
                    page.get_by_role('button', name='Send reply', exact=True).click()
                    expect(page.get_by_role('log')).to_contain_text('A synthetic clarification')
                    assert page.url == chat_url
                    page.screenshot(path=str(artifacts / ('conversation-' + str(width) + '.png')), full_page=True)
                    if width == 1440:
                        # A stale status response must not strand the newly selected conversation.
                        paused = []
                        page.route('**/api/chats/*', lambda route: paused.append(route), times=1)
                        with page.expect_request('**/api/chats/*'):
                            page.evaluate('void pollChat()')
                        modes.get_by_role('radio', name='Eureka', exact=True).click()
                        page.get_by_label('Your message', exact=True).fill('Synthetic idea while a status request is pending')
                        with page.expect_response('**/api/chats'):
                            page.get_by_role('button', name='Save idea', exact=True).click()
                        assert len(paused) == 1
                        paused[0].continue_()
                        expect(page.get_by_role('log')).to_contain_text('Synthetic idea while a status request is pending')
                    page.get_by_role('button', name='New conversation', exact=True).click()
                    expect(modes.get_by_role('radio', name='Secretary', exact=True)).to_have_attribute('aria-checked', 'true')
                    page.goto(address + '/chat?mode=initialize')
                    expect(modes.get_by_role('radio',name='Initialize',exact=True)).to_have_count(0)
                    expect(modes.get_by_role('radio',name='Secretary',exact=True)).to_have_attribute('aria-checked','true')
                    page.goto(address + '/gm.html')
                    expect(page.locator('#generate')).to_be_visible()
                    expect(page.locator('#initialize')).to_have_count(0)
                    page.goto(address + '/chat')
                    modes.get_by_role('radio', name='Secretary', exact=True).focus()
                    page.keyboard.press('ArrowRight')
                    expect(modes.get_by_role('radio', name='To-do', exact=True)).to_be_focused()
                    expect(page.locator('#conversation-history')).to_be_visible()
                    expect(page.locator('#conversation-history summary')).to_have_count(0)
                    assert page.locator('#chat-history a').count() > 0
                    assert page.evaluate("localStorage.length === 0 && Object.values(sessionStorage).every(raw => !raw.includes('Synthetic idea'))")
                    assert not errors, errors
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    results.append({'width': width, 'overflow': False, 'pageErrors': 0, 'refresh': 'same conversation',
                                    'modeSwitch': 'pass', 'keyboard': 'pass', 'privateBrowserStorage': 'references only'})
                    page.close()
                browser.close()
            assert (root / 'preserved-record.txt').read_text() == 'Preserved synthetic evidence'
        finally:
            process.terminate(); process.communicate(timeout=5)
    report = {'modelCalls': 0, 'agent': 'synthetic', 'setup': 'mock saved, default changed', 'checks': results,
              'composer': composer_checks, 'autogrow': autogrow_checks, 'highlight': highlight_checks, 'motion': motion_checks, 'uploads': upload_checks, 'images': image_checks, 'questions': question_checks, 'scroll': scroll_checks}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
