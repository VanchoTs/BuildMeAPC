document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('login-form') as HTMLFormElement;
    const signupForm = document.getElementById('signup-form') as HTMLFormElement;

    const API_URL = `http://${window.location.hostname}:5075/api/auth`; 

    async function checkPendingBuild() {
        const pendingBuildStr = localStorage.getItem('pendingBuildToSave');
        if (pendingBuildStr) {
            try {
                const build = JSON.parse(pendingBuildStr);
                const buildApiUrl = `http://${window.location.hostname}:5075/api/builds`;
                const response = await fetch(buildApiUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(build)
                });
                
                if (response.ok) {
                    localStorage.removeItem('pendingBuildToSave');
                    alert('Your pending build has been saved to My List!');
                    window.location.href = 'mylist.html';
                    return true;
                }
            } catch (err) {
                console.error('Failed to save pending build:', err);
            }
        }
        return false;
    }

    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(loginForm);
            const data = Object.fromEntries(formData.entries());

            try {
                const response = await fetch(`${API_URL}/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include', // Send and receive cookies
                    body: JSON.stringify(data)
                });

                if (response.ok) {
                    const result = await response.json();
                    localStorage.setItem('user', JSON.stringify({ 
                        name: result.fullName, 
                        email: result.email,
                        role: result.role 
                    }));
                    
                    const redirected = await checkPendingBuild();
                    if (!redirected) {
                        alert('Login successful!');
                        window.location.href = 'index.html';
                    }
                } else {
                    const error = await response.text();
                    alert(`Login failed: ${error}`);
                }
            } catch (err) {
                alert('Could not connect to the authentication server.');
            }
        });
    }

    if (signupForm) {
        signupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(signupForm);
            const data = Object.fromEntries(formData.entries());

            if (data.password !== data['confirm-password']) {
                alert('Passwords do not match!');
                return;
            }

            delete data['confirm-password'];

            try {
                const response = await fetch(`${API_URL}/register`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include', // Send and receive cookies
                    body: JSON.stringify({
                        fullName: data['full-name'],
                        email: data.email,
                        password: data.password
                    })
                });

                if (response.ok) {
                    const result = await response.json();
                    localStorage.setItem('user', JSON.stringify({ 
                        name: result.fullName, 
                        email: result.email,
                        role: result.role 
                    }));

                    const redirected = await checkPendingBuild();
                    if (!redirected) {
                        alert('Account created successfully!');
                        window.location.href = 'index.html';
                    }
                } else {
                    const error = await response.text();
                    alert(`Registration failed: ${error}`);
                }
            } catch (err) {
                alert('Could not connect to the authentication server.');
            }
        });
    }
});
