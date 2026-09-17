import {useEffect, useState} from 'react'


function useTheme() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem('theme') || 'dark'
  )

  useEffect(() => {
    document.documentElement.setAttribute(
      'data-bs-theme',
      theme
    )

    localStorage.setItem('theme', theme)
  }, [theme])

  const toggleTheme = () => {
    setTheme(current =>
      current === 'dark' ? 'light' : 'dark'
    )
  }

  return {
    theme,
    toggleTheme,
  }
}


export default useTheme
